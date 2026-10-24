import Foundation
import SwiftUI
import CoreLocation
import EmberCore

/// Owns the bundle, the state machine and the device services; the views read only from here.
@MainActor
public final class AppModel: ObservableObject {
    public static let autoRepeatS: TimeInterval = 45
    static let feedRefreshS: TimeInterval = 300

    // Bundle and profiles
    @Published public private(set) var bundle: EmberBundle?
    @Published public private(set) var loadError: String?
    @Published public private(set) var profiles: [ClientProfile] = []
    @Published public var selectedId: String? { didSet { UserDefaults.standard.set(selectedId, forKey: "selectedId") } }
    @Published public var caregiverMode: Bool { didSet { UserDefaults.standard.set(caregiverMode, forKey: "caregiverMode") } }
    @Published public private(set) var notice: String?

    // Device-runtime deadline
    @Published public private(set) var powerOutSince: Date?
    @Published public private(set) var leaveNow: String?

    // Navigation mirror (the machine is a plain class)
    @Published public private(set) var state: NavState = .home
    @Published public private(set) var tick = 0
    @Published public private(set) var feedNote: String?

    public let speaker = Speaker()
    public let voice = VoiceController()
    public let location = LocationService()
    public let compass = CompassService()

    public private(set) var machine: NavigatorStateMachine?
    private var processor: VoiceCommandProcessor?
    private var spokenSerial = -1
    private var repeatTimer: Timer?
    private var minuteTimer: Timer?
    private var leaveNowSpoken = false
    private var feed: ApifyFeed?
    private var lastFeedFetch: Date?
    let store = BundleStore()
    private lazy var profileStore = ProfileStore(support: store.support)

    public init() {
        caregiverMode = UserDefaults.standard.bool(forKey: "caregiverMode")
        selectedId = UserDefaults.standard.string(forKey: "selectedId")
        let t = UserDefaults.standard.double(forKey: "powerOutSince")
        powerOutSince = t > 0 ? Date(timeIntervalSince1970: t) : nil
    }

    // MARK: launch

    /// onAppear can fire again whenever the root view is rebuilt (e.g. the `.id(fontChoice)` key on font change);
    /// setup must run once or it leaks a second minuteTimer and resets the state machine mid-session.
    private var launched = false

    public func launch() {
        guard !launched else { return }
        launched = true
        Platform.activatePlaybackSession()
        profiles = profileStore.load()
        if selectedId == nil || !profiles.contains(where: { $0.id == selectedId }) { selectedId = profiles.first?.id }
        loadBundle()
        location.onFix = { [weak self] l in self?.gotFix(l) }
        location.start()
        compass.start()
        voice.requestAuthorization()
        voice.onlineChanged = { [weak self] up in self?.networkChanged(up) }
        minuteTimer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.periodic() }
        }
        periodic()
    }

    public func loadBundle() {
        do {
            let b = try store.load(county: selected?.county)
            bundle = b
            machine = NavigatorStateMachine(bundle: b)
            machine?.headingProvider = { [weak self] in self?.compass.heading }
            processor = VoiceCommandProcessor(matcher: IntentMatcher(b.config.intents), config: b.config)
            loadError = nil
            configureFeed()
        } catch {
            loadError = "\(error)"
        }
        speaker.configure(bundle: bundle, clientId: selectedId)
        configureCartesia()
        sync()
    }

    /// Re-read keys after Settings is saved.
    public func settingsChanged() {
        configureCartesia()
        configureFeed()
    }

    func configureCartesia() {
        speaker.online = voice.online
        if let key = KeychainStore.get(.cartesiaAPIKey) {
            if speaker.cartesia == nil { speaker.cartesia = CartesiaStream(apiKey: key) }
            speaker.voiceId = selected?.voice?.voiceId ?? KeychainStore.get(.cartesiaVoiceId)
            if voice.online { speaker.cartesia?.open() }
        } else {
            speaker.cartesia?.close()
            speaker.cartesia = nil
        }
    }

    func configureFeed() {
        guard let b = bundle, let ds = KeychainStore.get(.apifyDatasetId) else { feed = nil; return }
        feed = ApifyFeed(datasetId: ds, token: KeychainStore.get(.apifyToken), county: b.county,
                         cacheURL: store.support.appendingPathComponent("feed-\(b.county).json"))
        applyFeed(feed!.cached())
    }

    func networkChanged(_ up: Bool) {
        speaker.online = up
        if up { speaker.cartesia?.open(); refreshFeed(force: true) } else { speaker.cartesia?.close() }
    }

    // MARK: profiles

    public var selected: ClientProfile? { profiles.first { $0.id == selectedId } }

    public func addProfile(fromCode code: String) {
        do {
            let p = try QRPayload.parse(code)
            profiles.removeAll { $0.id == p.id }
            profiles.append(p)
            profileStore.save(profiles)
            selectedId = p.id
            notice = "Added \(p.name)."
            if let b = bundle, let c = p.county, c != b.county { notice = "Added \(p.name). The map on this phone is for \(b.county), not \(c)." }
            speaker.configure(bundle: bundle, clientId: selectedId)
        } catch {
            notice = "That code is not an Ember card. Try again."
        }
        speaker.speak([Utterance(notice ?? "Okay.")])
    }

    public func handleURL(_ url: URL) {
        if url.scheme == "ember" { addProfile(fromCode: url.absoluteString) }
    }

    public func removeProfile(_ id: String) {
        profiles.removeAll { $0.id == id }
        profileStore.save(profiles)
        if selectedId == id { selectedId = profiles.first?.id }
    }

    public func select(_ id: String) {
        selectedId = id
        speaker.configure(bundle: bundle, clientId: id)
        speaker.voiceId = selected?.voice?.voiceId ?? KeychainStore.get(.cartesiaVoiceId)
    }

    // MARK: power out

    public var powerIsOut: Bool { powerOutSince != nil }

    public func setPowerOut(_ on: Bool, at date: Date = Date()) {
        powerOutSince = on ? (powerOutSince ?? date) : nil
        UserDefaults.standard.set(powerOutSince?.timeIntervalSince1970 ?? 0, forKey: "powerOutSince")
        leaveNowSpoken = false
        periodic()
    }

    // MARK: derived for views

    public var fireAgeText: String {
        guard let t = bundle?.fireDataTimestamp else { return "Fire data: none on this phone" }
        return "Fire data from \(Timestamps.ageText(Date().timeIntervalSince(t)))"
    }

    public var fireIsStale: Bool { !(machine?.fireIsFresh ?? false) }

    public var displayText: String {
        if !speaker.currentText.isEmpty { return speaker.currentText }
        return machine?.utterances.first?.text ?? ""
    }

    public var fireBearingWord: String? {
        guard let m = machine, let b = m.dataFireBearing, m.fireIsFresh else { return nil }
        return Geo.directionWord(b, m.config.templates.directions)
    }

    // MARK: actions (buttons)

    public func start() {
        guard let c = selected else { return }
        if let county = c.county, bundle?.county != county { loadBundle() }
        guard let m = machine else { return }
        speaker.configure(bundle: bundle, clientId: c.id)
        if let l = location.location, usable(l) { m.setPosition(lat: l.coordinate.latitude, lon: l.coordinate.longitude) }
        refreshFeed(force: false)
        do { try m.start(client: c, caregiver: caregiverMode) } catch { notice = "\(error)" }
        sync()
    }

    public func confirmFire() { machine?.confirmFire(); sync() }

    public func pointAtSmoke() {
        guard let h = compass.heading else {
            speaker.speak([Utterance("Point the phone at the smoke and tap.")])
            return
        }
        machine?.point(bearing: h)
        sync()
    }

    /// Navigate/Choose "Point": the phone is pointed at new smoke; the fire bearing is updated and the route turns away.
    public func pointAtNewFire() {
        guard let h = compass.heading else {
            speaker.speak([Utterance("Point the phone at the smoke and tap.")])
            return
        }
        machine?.pointAtNewFire(bearing: h)
        sync()
    }

    /// "Fire ahead" without a bearing: the fire is where the user is heading (compass, else the route edge).
    public func fireAhead() { machine?.fireAhead(heading: compass.heading); sync() }

    public func go() { machine?.go(); sync() }
    public func other() { machine?.other(); sync() }
    public func cantMove() { machine?.cantMove(); sync() }
    public func blocked() { machine?.blockCurrent(); sync() }
    public func repeatInstruction() { machine?.repeatCurrent(); sync() }
    public func shelterNext() { machine?.shelterNext(); sync() }
    public func shelterBack() { machine?.shelterBack(); sync() }
    public func done() { machine?.done(); speaker.stop(); sync() }

    public func micTapped() {
        voice.toggle { [weak self] text in
            Task { @MainActor in await self?.heard(text) }
        }
    }

    func heard(_ transcript: String) async {
        guard let m = machine, let p = processor else { return }
        let t = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        if t.isEmpty {
            speaker.speak([Utterance(NavigatorStateMachine.sayAgain)])
            return
        }
        var agent: VoiceAgent? = nil
        if voice.online, let key = KeychainStore.get(.anthropicAPIKey) { agent = VoiceAgent(apiKey: key) }
        let ctx = VoiceAgent.Context(street: m.currentStreet(), instruction: m.utterances.first?.text)
        let r = await p.process(t, agent: agent, context: ctx) { m.resolveStreet($0, cross: $1) }
        if let say = r.say { speaker.speak([Utterance(say)]) }
        if let cmd = r.execute {
            switch cmd {
            case .intent(.slower): speaker.slower = true
            case .intent(.louder): speaker.volume = 1.0
            default: break
            }
            m.apply(cmd)
            sync()
        }
    }

    // MARK: GPS, timers

    /// A fix outside the county bundle (e.g. a demo far from the county) is ignored; the card's home point is used.
    func usable(_ l: CLLocation) -> Bool {
        bundle?.contains(lat: l.coordinate.latitude, lon: l.coordinate.longitude) ?? false
    }

    func gotFix(_ l: CLLocation) {
        guard let m = machine, usable(l) else { return }
        m.updatePosition(lat: l.coordinate.latitude, lon: l.coordinate.longitude)
        sync()
    }

    func periodic() {
        let now = Date()
        if let c = selected {
            // Before Start there is no live route: use the stamped plan's route A time if the bundle has it.
            let routeS = machine?.remainingRouteTimeS ?? bundle?.plan(clientId: c.id)?.choices.first?.route.timeS ?? 0
            let dt = DeviceTimer(devices: c.devices, powerOutSince: powerOutSince)
            if let r = dt.leaveNow(routeTimeS: routeS, now: now), let cfg = bundle?.config {
                leaveNow = DeviceTimer.leaveNowSentence(r, config: cfg)
                if !leaveNowSpoken {
                    leaveNowSpoken = true
                    Platform.haptic()
                    // the leave_now_dev sentence already starts with "Leave now."; speaking a standalone
                    // "Leave now." clip first would say it twice
                    speaker.speak([Utterance(leaveNow!, template: "leave_now_dev")])
                }
            } else {
                leaveNow = nil
            }
        }
        if voice.online, lastFeedFetch.map({ now.timeIntervalSince($0) > AppModel.feedRefreshS }) ?? true {
            refreshFeed(force: false)
        }
        tick += 1
    }

    func refreshFeed(force: Bool) {
        guard let feed, voice.online else { return }
        if !force, let t = lastFeedFetch, Date().timeIntervalSince(t) < 60 { return }
        lastFeedFetch = Date()
        Task { @MainActor in
            let r = await feed.fetch()
            self.applyFeed(r)
        }
    }

    func applyFeed(_ r: ApifyFeed.Result) {
        guard let m = machine, let s = r.situation else { return }
        feedNote = nil
        let here = location.location.flatMap { usable($0) ? $0 : nil }.map { ($0.coordinate.latitude, $0.coordinate.longitude) }
            ?? selected.flatMap { c in c.lat.flatMap { la in c.lon.map { (la, $0) } } }
        if let (la, lo) = here { m.feedBlocked = ApifyFeed.blockedEdges(s, graph: m.graph, lat: la, lon: lo) }
        // a feed closure that lands on the active route re-plans immediately; the user should not have to hit Blocked
        if m.state == .navigate, let p = m.progress, !m.feedBlocked.isDisjoint(with: p.route.edges) {
            m.replan(origin: nil)
        }
        if let o = ApifyFeed.outage(s, zip: selected?.zip), !powerIsOut {
            setPowerOut(true, at: r.fetchedAt ?? Date())
            feedNote = "Power outage reported for \(o.area)."
        }
        if let t = r.fetchedAt {
            let closures = m.feedBlocked.count
            feedNote = (feedNote.map { $0 + " " } ?? "") + "County feed from \(Timestamps.ageText(Date().timeIntervalSince(t))): \(closures) closure\(closures == 1 ? "" : "s") nearby."
        }
    }

    /// Mirror the machine and speak anything new (with a haptic on every new instruction).
    func sync() {
        guard let m = machine else { state = .home; return }
        state = m.state
        Platform.keepScreenOn(m.state == .navigate)
        if m.serial != spokenSerial {
            spokenSerial = m.serial
            if m.utterances.isEmpty {
                speaker.stop()
            } else {
                speaker.speak(m.utterances)
                Platform.haptic()
            }
            restartAutoRepeat()
        }
        tick += 1
    }

    /// Navigate repeats the current instruction every 45 s (not while "stop" is in effect).
    func restartAutoRepeat() {
        repeatTimer?.invalidate()
        guard machine?.state == .navigate else { return }
        repeatTimer = Timer.scheduledTimer(withTimeInterval: AppModel.autoRepeatS, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self, let m = self.machine, m.state == .navigate, !m.stopped,
                      let group = m.progress?.currentGroup, !group.isEmpty else { return }
                self.speaker.speak(group.map(Utterance.init))
                Platform.haptic()
            }
        }
    }
}
