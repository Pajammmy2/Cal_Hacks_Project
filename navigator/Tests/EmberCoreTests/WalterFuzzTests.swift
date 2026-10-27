import Foundation
import Testing
@testable import EmberCore

/// Deterministic generator so a failing seed can be replayed.
struct SplitMix64: RandomNumberGenerator {
    var state: UInt64
    init(seed: UInt64) { state = seed }
    mutating func next() -> UInt64 {
        state &+= 0x9E3779B97F4A7C15
        var z = state
        z = (z ^ (z >> 30)) &* 0xBF58476D1CE4E5B9
        z = (z ^ (z >> 27)) &* 0x94D049BB133111EB
        return z ^ (z >> 31)
    }
}

/// Random valid event sequences against the state machine; every spoken sentence must have a clip in the bundle
/// (full-string clip or every fragment of its template) and a bedbound client must never leave Home/Shelter.
enum Fuzz {
    /// `.whereAmI` is left out: it names whatever street is under the phone, and pregen records streets only within
    /// REROUTE_RADIUS_M of the planned routes, so a fix 2 km away is an open "needs recording", not a code bug.
    static let intents: [Intent] = [.blocked, .fire, .repeat, .slower, .louder, .pushing, .cantMove,
                                    .howLong, .whichWay, .stop, .yes, .no]

    struct Report { var steps = 0; var utterances = 0; var unique = Set<String>(); var missing = Set<String>(); var states = Set<NavState>() }

    static func clipExists(_ u: Utterance, bundle: EmberBundle, clientId: String) -> Bool {
        let audio = bundle.audioDir
        let dirs = [audio.appendingPathComponent("clients/\(clientId)"), audio]
        func has(_ text: String) -> Bool {
            dirs.contains { FileManager.default.fileExists(atPath: $0.appendingPathComponent("\(Hashing.clipKey(text)).mp3").path) }
        }
        if has(u.text) { return true }
        guard let t = u.template, let parts = bundle.config.phrases.fragments[t] else { return false }
        return parts.allSatisfy { has(SharedConfig.format($0, u.vars)) }
    }

    static func run(bundle: EmberBundle, client: ClientProfile, seed: UInt64, steps: Int, checkClips: Bool) throws -> Report {
        var rng = SplitMix64(seed: seed)
        var rep = Report()
        let m = NavigatorStateMachine(bundle: bundle)
        m.clock = { Timestamps.parse("2026-10-25T09:00:00Z")! }
        let home = (client.lat ?? 0, client.lon ?? 0)
        var last: [Utterance] = []
        func seen() {
            if m.utterances != last {
                last = m.utterances
                for u in last {
                    rep.utterances += 1; rep.unique.insert(u.text)
                    if checkClips, !clipExists(u, bundle: bundle, clientId: client.id) { rep.missing.insert(u.text) }
                }
            }
            rep.states.insert(m.state)
        }
        try m.start(client: client, caregiver: Bool.random(using: &rng)); seen()
        for _ in 0..<steps {
            rep.steps += 1
            switch Int.random(in: 0..<30, using: &rng) {
            case 0: try m.start(client: client, caregiver: Bool.random(using: &rng))
            case 1: m.confirmFire()
            case 2: m.skipFireDirection()
            case 3: m.point(bearing: Double.random(in: 0..<360, using: &rng))
            case 4: m.go()
            case 5: m.other()
            case 6: m.cantMove()
            case 7: m.requestBlocked()
            case 8: m.requestFire(heading: Bool.random(using: &rng) ? Double.random(in: 0..<360, using: &rng) : nil)
            case 9: m.requestStartOver()
            case 10: m.confirmPending()
            case 11: m.cancelPending()
            case 12: m.blockCurrent()
            case 13: m.fireAhead(heading: Bool.random(using: &rng) ? Double.random(in: 0..<360, using: &rng) : nil)
            case 14: _ = m.newFireWithoutCompass()
            case 15: m.pointAtNewFire(bearing: Double.random(in: 0..<360, using: &rng))
            case 16: m.shelterNext()
            case 17: m.shelterBack()
            case 18: m.done()
            case 19: m.goHome()
            case 20: m.repeatCurrent()
            case 21: m.demoStepping = Bool.random(using: &rng); _ = m.demoStep()
            case 22:                                                   // GPS jitter 5–30 m around home
                let d = Double.random(in: 5...30, using: &rng) / 111_000
                m.updatePosition(lat: home.0 + d * Double.random(in: -1...1, using: &rng), lon: home.1 + d * Double.random(in: -1...1, using: &rng))
            case 23:                                                   // well off the route / far from home
                m.updatePosition(lat: home.0 + Double.random(in: -0.02...0.02, using: &rng), lon: home.1 + Double.random(in: -0.02...0.02, using: &rng))
            case 24: m.setPosition(lat: home.0, lon: home.1)
            case 25: m.handle(intents.randomElement(using: &rng)!)
            case 26: m.cutEveryRoad()
            case 27: m.setVariant(pushed: Bool.random(using: &rng))
            case 28: m.replan(origin: nil)
            default: m.handle(intents.randomElement(using: &rng)!)
            }
            seen()
        }
        return rep
    }

    static let walter = ClientProfile(id: "c_walter", name: "Walter Briggs", mobility: "bedbound", transfer: "hoyer",
                                      devices: [ClientDevice(kind: "ventilator", hours: 8)],
                                      home: ClientHome(sleepRoom: "main bedroom"), lat: 39.7595, lon: -121.600637, county: "paradise")
}

@Suite struct WalterFuzzTests {
    /// Fake bundle (always on): no crash, and a bedbound client only ever sees Home and Shelter.
    @Test func bedboundFuzzNeverLeavesHomeOrShelter() throws {
        var total = 0
        for seed in 0..<20 {
            let r = try Fuzz.run(bundle: Fixtures.bundle, client: Fixtures.client("bedbound"), seed: UInt64(seed), steps: 500, checkClips: false)
            total += r.steps
            #expect(r.states.isSubset(of: [.home, .shelter]), "seed \(seed) reached \(r.states)")
        }
        #expect(total == 10_000)
    }

    /// Real Paradise bundle: EMBER_REAL_BUNDLE=/path/to/bundles/paradise swift test --filter WalterFuzz
    /// Every sentence the machine can produce for Walter must have a Henry clip.
    @Test(.enabled(if: ProcessInfo.processInfo.environment["EMBER_REAL_BUNDLE"] != nil))
    func realBundleWalterEverySentenceHasAClip() throws {
        let dir = URL(fileURLWithPath: ProcessInfo.processInfo.environment["EMBER_REAL_BUNDLE"]!)
        let bundle = try EmberBundle(dir: dir, sharedFallback: Fixtures.sharedDir)
        var utterances = 0, unique = Set<String>(), missing = Set<String>(), states = Set<NavState>()
        for seed in 0..<10 {
            let r = try Fuzz.run(bundle: bundle, client: Fuzz.walter, seed: UInt64(seed), steps: 1000, checkClips: true)
            utterances += r.utterances; unique.formUnion(r.unique); missing.formUnion(r.missing); states.formUnion(r.states)
        }
        print("WALTER FUZZ: 10 seeds x 1000 steps, \(utterances) utterances, \(unique.count) unique sentences, states \(states), missing \(missing.count)")
        for t in unique.sorted() { print("  SAID \(Hashing.clipKey(t)) \(t)") }
        for t in missing.sorted() { print("  MISSING \(Hashing.clipKey(t)) \(t)") }
        #expect(missing.isEmpty, "no clip for: \(missing.sorted())")
        #expect(states.isSubset(of: [.home, .shelter]), "Walter reached \(states)")
    }
}
