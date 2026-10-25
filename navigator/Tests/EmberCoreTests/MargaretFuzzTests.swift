import Foundation
import Testing
@testable import EmberCore

/// Overnight audio audit (c_margaret): random valid event sequences against the REAL Paradise bundle, asserting that
/// every `Utterance` the state machine emits has a recorded Henry clip (full-string clip, or every fragment of its
/// template). Any miss is printed with its exact text and clip key.
/// EMBER_REAL_BUNDLE=/path/to/bundles/paradise swift test --filter MargaretFuzz
@Suite struct MargaretFuzzTests {
    static let card = "ember://p/paradise/eyJ2IjoxLCJpZCI6ImNfbWFyZ2FyZXQiLCJuYW1lIjoiTWFyZ2FyZXQgTydOZWlsIiwibW9iaWxpdHkiOiJ3YWxrZXIiLCJ0cmFuc2ZlciI6Im9uZV9wZXJzb25fYXNzaXN0IiwiZGV2aWNlcyI6W3sia2luZCI6ImNwYXAiLCJob3VycyI6bnVsbCwiYmF0dGVyeV9wY3QiOm51bGx9XSwidmlzaW9uIjoibG93X3Zpc2lvbiIsImhlYXJpbmciOiJub3JtYWwiLCJjb2duaXRpb24iOiJzaW1wbGVfc3RlcHMiLCJsYW5ndWFnZSI6ImVuIiwiaG9tZSI6eyJzbGVlcF9yb29tIjoiYmVkcm9vbSBhdCB0aGUgZW5kIG9mIHRoZSBoYWxsIiwicGV0cyI6IlR3byBjYXRzIiwiY2hhaXJfbG9jYXRpb24iOiJXYWxrZXIgYnkgdGhlIGJlZCJ9LCJsYXQiOjM5LjczODk4NywibG9uIjotMTIxLjYyOTQ1MSwicmVmdWdlX2lkcyI6WyJyX3c2MDQ2Mjg2MTAiLCJyX3c0ODA5NDI1ODIiXSwiemlwIjoiOTU5NjkifQ=="

    struct Rng {
        var s: UInt64
        mutating func next() -> UInt64 { s ^= s << 13; s ^= s >> 7; s ^= s << 17; return s }
        mutating func int(_ n: Int) -> Int { Int(next() % UInt64(n)) }
        mutating func double() -> Double { Double(next() % 1_000_000) / 1_000_000 }
        mutating func bool() -> Bool { next() & 1 == 0 }
    }

    /// Clip check identical to Speaker.playOne: full clip in audio/ (or the clone dir), else every fragment clip.
    static func hasClip(_ u: Utterance, bundle: EmberBundle, clientId: String) -> Bool {
        let fm = FileManager.default
        let dirs = [bundle.audioDir.appendingPathComponent("clients/\(clientId)"), bundle.audioDir]
        func clip(_ text: String, _ dir: URL) -> Bool { fm.fileExists(atPath: dir.appendingPathComponent("\(Hashing.clipKey(text)).mp3").path) }
        if dirs.contains(where: { clip(u.text, $0) }) { return true }
        if let t = u.template, let parts = bundle.config.phrases.fragments[t] {
            let texts = parts.map { SharedConfig.format($0, u.vars) }
            if dirs.contains(where: { d in texts.allSatisfy { clip($0, d) } }) { return true }
        }
        return false
    }

    final class Audit {
        var exercised = 0
        var misses: [String: (Utterance, String)] = [:]   // key -> (utterance, where)
        var states: [String: Int] = [:]
        var fragmentOnly = 0
        func check(_ m: NavigatorStateMachine, bundle: EmberBundle, clientId: String, lastSerial: inout Int, where ctx: String) {
            guard m.serial != lastSerial else { return }
            lastSerial = m.serial
            states[m.state.rawValue, default: 0] += 1
            for u in m.utterances {
                exercised += 1
                #expect(!u.text.isEmpty, "empty utterance at \(ctx)")
                if !MargaretFuzzTests.hasClip(u, bundle: bundle, clientId: clientId) {
                    misses[Hashing.clipKey(u.text)] = (u, ctx)
                }
            }
        }
    }

    static func bundle() throws -> EmberBundle {
        let dir = URL(fileURLWithPath: ProcessInfo.processInfo.environment["EMBER_REAL_BUNDLE"]!)
        return try EmberBundle(dir: dir, sharedFallback: Fixtures.sharedDir)
    }

    /// A point `offM` metres from a random point of the current route (or of the home), at a random bearing.
    static func jitter(_ m: NavigatorStateMachine, offM: Double, rng: inout Rng) -> (lat: Double, lon: Double)? {
        let base: (lat: Double, lon: Double)
        if let p = m.progress {
            base = p.point(atM: rng.double() * p.totalM, graph: m.graph)
        } else if let c = m.client, let la = c.lat, let lo = c.lon {
            base = (la, lo)
        } else { return nil }
        let b = rng.double() * 360 * .pi / 180
        let dLat = offM * cos(b) / 111_320.0
        let dLon = offM * sin(b) / (111_320.0 * cos(base.lat * .pi / 180))
        return (base.lat + dLat, base.lon + dLon)
    }

    static let pointOnRoute = 0

    @Test(.enabled(if: ProcessInfo.processInfo.environment["EMBER_REAL_BUNDLE"] != nil))
    func everyUtteranceHasAHenryClip() throws {
        let bundle = try MargaretFuzzTests.bundle()
        let client = try QRPayload.parse(MargaretFuzzTests.card)
        #expect(client.id == "c_margaret")
        let fresh = bundle.fireDataTimestamp.map { $0.addingTimeInterval(600) } ?? Date()
        let stale = fresh.addingTimeInterval(7 * 3600)
        let audit = Audit()
        let runs = Int(ProcessInfo.processInfo.environment["EMBER_FUZZ_RUNS"] ?? "") ?? 60
        let stepsPerRun = Int(ProcessInfo.processInfo.environment["EMBER_FUZZ_STEPS"] ?? "") ?? 120
        var eventCounts: [String: Int] = [:]
        // EMBER_FUZZ_MODE=demo: no GPS jitter and no teleport to the refuge, i.e. only what buttons on a desk can do
        let demoOnly = ProcessInfo.processInfo.environment["EMBER_FUZZ_MODE"] == "demo"
        var rng = Rng(s: 0x9E3779B97F4A7C15)
        var totalSteps = 0
        for run in 0..<runs {
            let m = NavigatorStateMachine(bundle: bundle)
            let clock = run % 2 == 0 ? fresh : stale
            m.clock = { clock }
            var heading: Double? = rng.bool() ? rng.double() * 360 : nil
            m.headingProvider = { heading }
            var serial = m.serial
            var pos = (lat: client.lat!, lon: client.lon!)
            m.setPosition(lat: pos.lat, lon: pos.lon)
            for step in 0..<stepsPerRun {
                let ctx = "run \(run) step \(step) state \(m.state)"
                var ev = ""
                switch m.state {
                case .home:
                    ev = "start"; try m.start(client: client, caregiver: rng.bool())
                case .whichWay:
                    switch rng.int(12) {
                    case 0...3: ev = "point"; m.point(bearing: rng.double() * 360)
                    case 4, 5: ev = "confirmFire"; m.confirmFire(); if m.state == .whichWay { ev = "skip"; m.skipFireDirection() }
                    case 6, 7: ev = "skipFireDirection"; m.skipFireDirection()
                    case 8: ev = "cantMove"; m.cantMove()
                    case 9: ev = "repeat"; m.repeatCurrent()
                    case 10: ev = "goHome"; m.goHome()
                    default: ev = "intent"; m.handle([Intent.louder, .slower, .whereAmI, .howLong, .yes, .no, .stop][rng.int(7)])
                    }
                case .choose:
                    switch rng.int(16) {
                    case 0...4: ev = "go"; m.go()
                    case 5, 6: ev = "other"; m.other()
                    case 7: ev = "cantMove"; m.cantMove()
                    case 8: ev = "requestFire"; m.requestFire(heading: heading); if rng.bool() { m.confirmPending() } else { m.cancelPending() }
                    case 9: ev = "pointAtNewFire"; m.pointAtNewFire(bearing: rng.double() * 360)
                    case 10: ev = "newFireNoCompass"; m.newFireWithoutCompass()
                    case 11: ev = "startOver"; m.requestStartOver(); if rng.bool() { m.confirmPending() } else { m.cancelPending() }
                    case 12: ev = "repeat"; m.repeatCurrent()
                    case 13 where !demoOnly: ev = "jitter"; if let j = MargaretFuzzTests.jitter(m, offM: rng.double() * 30, rng: &rng) { pos = j; m.updatePosition(lat: j.lat, lon: j.lon) }
                    default: ev = "intent"; m.handle([Intent.louder, .slower, .whereAmI, .howLong, .whichWay, .yes, .no, .fire, .blocked, .repeat][rng.int(10)])
                    }
                case .navigate:
                    switch rng.int(30) {
                    case 0...2: ev = "blocked"; m.requestBlocked(); if rng.int(4) > 0 { m.confirmPending() } else { m.cancelPending() }
                    case 3: ev = "blockCurrent"; m.blockCurrent()
                    case 4, 5: ev = "fireAhead"; m.fireAhead(heading: rng.bool() ? rng.double() * 360 : nil)
                    case 6: ev = "pointAtNewFire"; m.pointAtNewFire(bearing: rng.double() * 360)
                    case 7: ev = "newFireNoCompass"; m.newFireWithoutCompass()
                    case 8: ev = "requestFire"; m.requestFire(heading: heading); if rng.bool() { m.confirmPending() } else { m.cancelPending() }
                    case 9: ev = "cantMove"; m.cantMove()
                    case 10, 11: ev = "repeat"; m.repeatCurrent()
                    case 12: ev = "louder"; m.handle(.louder)
                    case 13: ev = "slower"; m.handle(.slower)
                    case 14: ev = "startOver"; m.requestStartOver(); if rng.int(3) == 0 { m.confirmPending() } else { m.cancelPending() }
                    case 15...19:
                        ev = "demoStep"; m.demoStepping = true; m.demoStep(); m.demoStepping = rng.bool()
                        if let p = m.position { pos = p }
                    case 20...23 where !demoOnly:
                        let off = rng.int(3) == 0 ? 30 + rng.double() * 120 : 5 + rng.double() * 25
                        ev = off > 30 ? "jitterFar" : "jitterNear"
                        if let j = MargaretFuzzTests.jitter(m, offM: off, rng: &rng) { pos = j; m.demoStepping = false; m.updatePosition(lat: j.lat, lon: j.lon) }
                    case 24: ev = "cutEveryRoad"; m.cutEveryRoad()
                    case 25: ev = "intent"; m.handle([Intent.whereAmI, .howLong, .whichWay, .stop, .yes, .no, .pushing, .cantMove][rng.int(8)])
                    case 26: ev = "atRefuge"; m.setStatus("at_refuge")
                    case 27 where !demoOnly:
                        ev = "arrive"
                        if let r = m.currentChoice?.refuge, let e = r.entryPoints.first { m.demoStepping = false; m.updatePosition(lat: e.lat, lon: e.lon); pos = (e.lat, e.lon) }
                    case 28: ev = "heading"; heading = rng.bool() ? rng.double() * 360 : nil
                    default: ev = "setVariant"; m.setVariant(pushed: rng.bool())
                    }
                case .shelter:
                    switch rng.int(8) {
                    case 0...3: ev = "shelterNext"; m.shelterNext()
                    case 4: ev = "shelterBack"; m.shelterBack()
                    case 5: ev = "repeat"; m.repeatCurrent()
                    case 6: ev = "cantMove"; m.cantMove()
                    default: ev = "intent"; m.handle([Intent.louder, .slower, .cantMove, .blocked, .fire, .howLong, .whereAmI][rng.int(7)])
                    }
                case .arrived:
                    switch rng.int(4) {
                    case 0, 1: ev = "done"; m.done()
                    case 2: ev = "repeat"; m.repeatCurrent()
                    default: ev = "intent"; m.handle([Intent.louder, .blocked, .fire, .howLong, .whereAmI, .cantMove][rng.int(6)])
                    }
                case .stayHere:
                    switch rng.int(4) {
                    case 0: ev = "goHome"; m.goHome()
                    case 1: ev = "repeat"; m.repeatCurrent()
                    default: ev = "intent"; m.handle([Intent.louder, .blocked, .fire, .howLong, .whereAmI, .cantMove, .repeat][rng.int(7)])
                    }
                }
                eventCounts[ev, default: 0] += 1
                totalSteps += 1
                audit.check(m, bundle: bundle, clientId: client.id, lastSerial: &serial, where: "\(ctx) after \(ev)")
                _ = pos
            }
        }
        print("FUZZ c_margaret: \(totalSteps) steps, \(audit.exercised) utterances, \(audit.misses.count) without a clip; states \(audit.states.sorted { $0.key < $1.key }); events \(eventCounts.sorted { $0.key < $1.key })")
        for (k, (u, ctx)) in audit.misses.sorted(by: { $0.key < $1.key }) {
            print("MISS \(k) | \(u.text) | template=\(u.template ?? "-") | \(ctx)")
        }
        #expect(audit.misses.isEmpty, "\(audit.misses.count) utterances have no clip: \(audit.misses.values.map(\.0.text).sorted())")
    }
}
