import Foundation
import Testing
@testable import EmberCore

/// Overnight audio audit for Rosa Delgado (manual chair, Spanish card, English voice): seeded-random event sequences
/// against the REAL Paradise bundle, asserting every `Utterance.text` the state machine emits has a recorded clip
/// (full-string clip, or every fragment of its template). Any miss is the exact sentence that would reach the Apple
/// voice. EMBER_REAL_BUNDLE=/path/to/bundles/paradise swift test --filter RosaFuzz
@Suite struct RosaFuzzAudioTests {
    static let env = ProcessInfo.processInfo.environment
    static let real = env["EMBER_REAL_BUNDLE"].map { URL(fileURLWithPath: $0) }

    static func rosa() -> ClientProfile {
        var c = ClientProfile(id: "c_rosa", name: "Rosa Delgado", mobility: "manual_chair", transfer: "slide_board", devices: [],
                              home: ClientHome(sleepRoom: "back bedroom", pets: "One small dog (Coco)", chairLocation: "By the front door"),
                              lat: 39.752223, lon: -121.611556, county: "paradise")
        c.language = "es"; c.refugeIds = ["r_w604628610", "r_w480942582"]; c.zip = "95969"
        return c
    }

    /// Mirrors Speaker.playOne's lookup (EmberApp): full clip in audio/, else every fragment of the template.
    static func hasClip(_ u: Utterance, audio: URL, config: SharedConfig) -> Bool {
        let fm = FileManager.default
        func clip(_ t: String) -> Bool { fm.fileExists(atPath: audio.appendingPathComponent("\(Hashing.clipKey(t)).mp3").path) }
        if clip(u.text) { return true }
        guard let t = u.template, let parts = config.phrases.fragments[t] else { return false }
        return parts.allSatisfy { clip(SharedConfig.format($0, u.vars)) }
    }

    struct LCG { var s: UInt64; mutating func next() -> UInt64 { s = s &* 6364136223846793005 &+ 1442695040888963407; return s >> 33 }
        mutating func int(_ n: Int) -> Int { Int(next() % UInt64(n)) }
        mutating func double() -> Double { Double(next() % 1_000_000) / 1_000_000 } }

    /// 5–30 m off the route point (GPS jitter).
    static func jitter(_ p: (lat: Double, lon: Double), _ r: inout LCG) -> (Double, Double) {
        let m = 5 + r.double() * 25, b = r.double() * 2 * .pi
        return (p.lat + m * cos(b) / 111_320, p.lon + m * sin(b) / (111_320 * cos(p.lat * .pi / 180)))
    }

    @Test(.enabled(if: real != nil))
    func thousandsOfRandomEventsForRosaNeverReachTheAppleVoice() throws {
        let bundle = try EmberBundle(dir: RosaFuzzAudioTests.real!, sharedFallback: Fixtures.sharedDir)
        let audio = bundle.audioDir
        let g = bundle.graph
        let fireT = bundle.fireDataTimestamp ?? Date()
        let clocks: [(String, Date)] = [("fresh", fireT.addingTimeInterval(3600)), ("stale", fireT.addingTimeInterval(24 * 3600))]
        var misses: [String: String] = [:]      // text -> first event that produced it
        var distinct = Set<String>(), total = 0, events = 0, stateVisits: [NavState: Int] = [:]

        for (clockName, now) in clocks {
            for seed in 1...40 {
                var r = LCG(s: UInt64(seed) &* 7919 &+ (clockName == "fresh" ? 0 : 1))
                let m = NavigatorStateMachine(bundle: bundle)
                m.clock = { now }
                var lastSerial = -1
                func grab(_ ev: String) {
                    guard m.serial != lastSerial else { return }
                    lastSerial = m.serial
                    for u in m.utterances {
                        total += 1; distinct.insert(u.text)
                        if !RosaFuzzAudioTests.hasClip(u, audio: audio, config: bundle.config), misses[u.text] == nil {
                            misses[u.text] = "\(clockName) seed \(seed) \(ev) state=\(m.state) template=\(u.template ?? "-")"
                        }
                    }
                }
                try m.start(client: RosaFuzzAudioTests.rosa(), caregiver: seed % 3 == 0); grab("start")
                for _ in 0..<400 {
                    events += 1
                    stateVisits[m.state, default: 0] += 1
                    if m.state == .home { try m.start(client: RosaFuzzAudioTests.rosa(), caregiver: r.int(2) == 0); grab("restart"); continue }
                    if m.state == .shelter, r.int(2) == 0 { m.done(); grab("done-shelter"); continue }
                    let k = r.int(30)
                    switch k {
                    case 0: m.point(bearing: Double(r.int(360))); grab("point")
                    case 1: m.confirmFire(); grab("confirmFire")
                    case 2: m.skipFireDirection(); grab("notSure")
                    case 3, 4: m.go(); grab("go")
                    case 5: m.other(); grab("other")
                    case 6: m.requestBlocked(); grab("blocked?"); if r.int(4) > 0 { m.confirmPending(); grab("blocked-yes") } else { m.cancelPending(); grab("blocked-no") }
                    case 7: m.blockCurrent(); grab("blockCurrent")
                    case 8: m.requestFire(heading: r.int(2) == 0 ? nil : Double(r.int(360))); grab("fire?"); m.confirmPending(); grab("fire-yes")
                    case 9: m.pointAtNewFire(bearing: Double(r.int(360))); grab("pointNewFire")
                    case 10: m.newFireWithoutCompass(); grab("newFireNoCompass")
                    case 11: m.fireAhead(heading: r.int(2) == 0 ? nil : Double(r.int(360))); grab("fireAhead")
                    case 12: if r.int(25) == 0 { m.cantMove(); grab("cantMove") }
                    case 13: m.repeatCurrent(); grab("repeat")
                    case 14: m.handle(.louder); grab("louder")
                    case 15: m.handle(.slower); grab("slower")
                    case 16: if r.int(12) == 0 { m.requestStartOver(); grab("startOver?"); m.confirmPending(); grab("startOver-yes") } else { m.requestStartOver(); grab("startOver?"); m.cancelPending(); grab("startOver-no") }
                    case 17: m.shelterNext(); grab("shelterNext")
                    case 18: m.shelterBack(); grab("shelterBack")
                    case 19, 20, 21:
                        m.demoStepping = true; m.demoStep(); grab("demoStep"); m.demoStepping = false
                    case 22, 23:
                        if let p = m.progress, m.state == .navigate {
                            let i = min(p.edgeOffset + r.int(2), p.route.nodes.count - 1)
                            let n = p.route.nodes[i]
                            let (la, lo) = RosaFuzzAudioTests.jitter((g.lat[n], g.lon[n]), &r)
                            m.updatePosition(lat: la, lon: lo); grab("jitter")
                        } else if let c = m.client, let la = c.lat, let lo = c.lon {
                            let (jla, jlo) = RosaFuzzAudioTests.jitter((la, lo), &r)
                            m.updatePosition(lat: jla, lon: jlo); grab("jitterHome")
                        }
                    case 24: for i in Intent.allCases { m.handle(i); grab("intent-\(i)") }
                    case 25: m.setVariant(pushed: r.int(2) == 0); grab("variant")
                    case 26: if r.int(60) == 0 { m.cutEveryRoad(); grab("cutEveryRoad") }
                    case 27: if let c = m.currentChoice, m.state == .navigate, let ep = c.refuge.entryPoints.first { m.updatePosition(lat: ep.lat, lon: ep.lon); grab("arrive") }
                    case 28: if m.state == .arrived || m.state == .stayHere || (m.state == .shelter && r.int(3) == 0) { m.done(); grab("done") }
                    default:
                        if let p = m.progress, m.state == .navigate {   // walk forward along the route, exactly on a node
                            let n = p.route.nodes[min(p.edgeOffset + 1, p.route.nodes.count - 1)]
                            m.updatePosition(lat: g.lat[n], lon: g.lon[n]); grab("walk")
                        }
                    }
                }
            }
        }
        print("ROSA FUZZ: \(events) events, \(total) utterances, \(distinct.count) distinct texts, states \(stateVisits), misses \(misses.count)")
        for (t, w) in misses.sorted(by: { $0.key < $1.key }) { print("  MISS \(Hashing.clipKey(t)) \"\(t)\"  <- \(w)") }
        #expect(misses.isEmpty, "\(misses.count) sentences have no clip: \(misses.keys.sorted())")
        #expect(events > 30_000)
    }
}
