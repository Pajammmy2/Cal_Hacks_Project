import Foundation
import Testing
@testable import EmberCore

/// Audit tool, not a pass/fail test: drives NavigatorStateMachine through scripted and seeded-random
/// flows and writes every distinct utterance (text, template, vars) to /tmp/ember_utterances.json
/// so the voice-coverage audit can compare against the pre-generated clip set.
@Suite struct HarvestTests {
    struct Seen: Codable { var text: String; var template: String?; var vars: [String: String] }
    var seen: [String: Seen] = [:]
    var utterCount = 0

    mutating func grab(_ m: NavigatorStateMachine, _ tag: String) {
        for u in m.utterances {
            utterCount += 1
            if seen[u.text] == nil { seen[u.text] = Seen(text: u.text, template: u.template, vars: u.vars) }
        }
    }

    func machine(_ now: Date?) -> NavigatorStateMachine {
        let m = NavigatorStateMachine(bundle: Fixtures.bundle)
        if let now { m.clock = { now } }
        return m
    }

    @Test func harvest() throws {
        var h = HarvestTests()
        let fresh = Timestamps.parse("2026-10-23T13:00:00Z")!
        let stale = Timestamps.parse("2026-10-23T19:00:00Z")!
        let g = Fixtures.bundle.graph
        let intents: [Intent] = Intent.allCases
        let mobilities = ["manual_chair", "power_chair", "walker", "cane", "bedbound"]

        for mobility in mobilities {
            for node in [0, 60, 112, 200, 400, 640] where node < g.lat.count {
                for now in [fresh, stale] {
                    let m = h.machine(now)
                    try? m.start(client: Fixtures.client(mobility, node: node), caregiver: false)
                    h.grab(m, "start")
                    if m.state == .shelter {
                        for _ in 0..<10 { m.shelterNext(); h.grab(m, "shelter") }
                        for _ in 0..<10 { m.shelterBack(); h.grab(m, "shelterBack") }
                        continue
                    }
                    m.confirmFire(); h.grab(m, "confirm")
                    m.point(bearing: 45); h.grab(m, "point")
                    m.point(bearing: 270); h.grab(m, "point2")
                    for _ in 0..<12 { m.other(); h.grab(m, "other") }
                    for i in intents { m.handle(i); h.grab(m, "intent-choose-\(i)") }
                    if m.state != .choose { continue }
                    m.go(); h.grab(m, "go")
                    // Walk the route, firing every intent at every other node.
                    var steps = 0
                    while m.state == .navigate, let p = m.progress, steps < 500 {
                        let i = min(p.edgeOffset, p.route.nodes.count - 1)
                        let n = p.route.nodes[i]
                        m.updatePosition(lat: g.lat[n], lon: g.lon[n])
                        h.grab(m, "walk")
                        if steps % 2 == 0 { for i in intents { m.handle(i); h.grab(m, "intent-nav-\(i)") } }
                        steps += 1
                        if m.state == .arrived || m.state == .shelter { break }
                        if steps > 0, steps % 3 == 0 { m.blockCurrent(); h.grab(m, "blocked") }
                        if steps % 5 == 0 { m.pointAtNewFire(bearing: Double(steps * 37 % 360)); h.grab(m, "newfire") }
                        if steps % 7 == 0 { m.fireAhead(); h.grab(m, "fireahead") }
                    }
                    for i in intents { m.handle(i); h.grab(m, "intent-end-\(i)") }
                    for _ in 0..<10 { m.shelterNext(); h.grab(m, "shelter2") }
                    m.done(); h.grab(m, "done")
                }
            }
        }

        // whereAmI on every street: place the user at each edge's midpoint.
        let w = h.machine(stale)
        try? w.start(client: Fixtures.client("walker", node: 0), caregiver: false)
        for (i, e) in g.edges.enumerated() {
            w.setPosition(lat: (g.lat[e.a] + g.lat[e.b]) / 2, lon: (g.lon[e.a] + g.lon[e.b]) / 2)
            w.handle(.whereAmI)
            h.grab(w, "where-\(i)")
        }
        // Every display-name cue text the router can emit for streets near the routes.
        let streets = Array(Set(g.edges.map { Cues.displayName($0, Fixtures.config.templates) })).sorted()
        let refugeNames = Fixtures.bundle.refuges.map(\.name)
        for t in Cues(graph: g, config: Fixtures.config).allCueTexts(streets: streets, refugeNames: refugeNames) {
            if h.seen[t] == nil { h.seen[t] = Seen(text: t, template: nil, vars: [:]) }
        }
        // fixed phrases + templates filled across the whole grid, as the state machine formats them.
        let cfg = Fixtures.config
        for s in cfg.phrases.fixed { if h.seen[s] == nil { h.seen[s] = Seen(text: s, template: nil, vars: [:]) } }
        for d in cfg.templates.directions {
            for key in ["fire_dir", "fire_is", "which_way"] {
                let t = cfg.phrase(key, ["direction": d])
                if h.seen[t] == nil { h.seen[t] = Seen(text: t, template: key, vars: ["direction": d]) }
            }
        }
        for s in streets {
            for key in ["blocking", "where"] {
                let t = cfg.phrase(key, ["street": s])
                if h.seen[t] == nil { h.seen[t] = Seen(text: t, template: key, vars: ["street": s]) }
            }
        }
        // shelter fallback steps for a few room names (plan-missing path).
        for room in ["bedroom", "back bedroom", "kitchen", "den", "living room"] {
            var c2 = Fixtures.client("walker", node: 0)
            c2.home = ClientHome(sleepRoom: room)
            let sh = PlanText.shelterSteps(c2)
            for s in sh.steps { if h.seen[s] == nil { h.seen[s] = Seen(text: s, template: nil, vars: [:]) } }
        }

        // Fuzz: seeded random action sequences; crash = test failure, utterances harvested too.
        var rngState: UInt64 = 0xE4BE2
        func next(_ bound: Int) -> Int {
            rngState = rngState &* 6364136223846793005 &+ 1442695040888963407
            return Int((rngState >> 33) % UInt64(bound))
        }
        for iter in 0..<400 {
            let m = h.machine(iter % 2 == 0 ? fresh : stale)
            let mob = mobilities[next(mobilities.count)]
            try? m.start(client: Fixtures.client(mob, node: next(640)), caregiver: next(2) == 0)
            h.grab(m, "fuzz-start")
            for _ in 0..<60 {
                switch next(14) {
                case 0: m.confirmFire()
                case 1: m.point(bearing: Double(next(360)))
                case 2: m.go()
                case 3: m.other()
                case 4: m.cantMove()
                case 5: m.blockCurrent()
                case 6: m.fireAhead()
                case 7: m.pointAtNewFire(bearing: Double(next(360)))
                case 8: m.shelterNext()
                case 9: m.shelterBack()
                case 10: m.done()
                case 11: m.repeatCurrent()
                case 12:
                    if let p = m.progress, !p.route.nodes.isEmpty {
                        let n = p.route.nodes[next(p.route.nodes.count)]
                        m.updatePosition(lat: g.lat[n], lon: g.lon[n])
                    } else {
                        let n = next(g.lat.count)
                        m.updatePosition(lat: g.lat[n], lon: g.lon[n])
                    }
                default: m.handle(Intent.allCases[next(Intent.allCases.count)])
                }
                h.grab(m, "fuzz")
            }
        }

        let out = try JSONSerialization.data(withJSONObject: h.seen.values.map {
            ["text": $0.text, "template": $0.template as Any, "vars": $0.vars]
        }, options: [.sortedKeys])
        try out.write(to: URL(fileURLWithPath: "/tmp/ember_utterances.json"))
        print("HARVEST \(h.seen.count) unique strings, \(h.utterCount) utterances")
        #expect(h.seen.count > 100)
    }
}
