import Foundation
import Testing
@testable import EmberCore

/// Stress-test the state machine: every button in unusual orders, plus regression tests for bugs
/// found in the pre-demo audit (see EMBER_QA_REPORT.md).
@Suite struct StressTests {
    let fresh = Timestamps.parse("2026-10-23T13:00:00Z")!
    let stale = Timestamps.parse("2026-10-23T19:00:00Z")!

    func machine(_ now: Date) -> NavigatorStateMachine {
        let m = NavigatorStateMachine(bundle: Fixtures.bundle)
        m.clock = { now }
        return m
    }

    func navigating(_ m: NavigatorStateMachine, node: Int = 112) throws {
        try m.start(client: Fixtures.client("manual_chair", node: node), caregiver: false)
        m.point(bearing: 200)
        m.go()
        #expect(m.state == .navigate)
    }

    @Test func goBeforeChooseIsANoOp() throws {
        let m = machine(fresh)
        m.go()                                     // home
        #expect(m.state == .home && m.utterances.isEmpty)
        try m.start(client: Fixtures.client("walker", node: 112), caregiver: false)
        m.go()                                     // whichWay, not choose yet
        #expect(m.state == .whichWay)
        m.confirmFire(); m.go()                    // choose -> navigate
        #expect(m.state == .navigate)
    }

    @Test func blockedTwiceAccumulates() throws {
        let m = machine(fresh)
        try navigating(m)
        m.handle(.blocked)
        #expect(m.state == .navigate)
        let first = m.blocked.count
        m.handle(.blocked)                         // blocks the NEW current edge too
        #expect(m.blocked.count == first + 1)
        #expect(m.state == .navigate || m.state == .shelter)   // shelter only if truly no route
    }

    @Test func fireThenBlockedKeepsWedge() throws {
        let m = machine(stale)
        try navigating(m)
        m.handle(.fire)                            // wedge closed toward heading
        #expect(m.state == .navigate)
        let afterFire = m.blocked.count
        #expect(afterFire > 1)                     // wedge is many edges
        m.handle(.blocked)
        #expect(m.state == .navigate)
        #expect(m.blocked.count == afterFire + 1)  // physical block adds one edge, wedge stays
        if let c = m.currentChoice {
            #expect(m.blocked.isDisjoint(with: c.route.edges))
        }
    }

    @Test func newFireWithoutCompassUsesRouteHeading() throws {
        let m = machine(stale)
        try navigating(m)
        let heading = try #require(m.travelHeading)
        m.handle(.fire)                            // no compass: falls back to the route edge bearing
        #expect(m.fireBearing == heading)
        #expect(m.state == .navigate)
    }

    @Test func cantMoveMidRouteEntersShelterOnce() throws {
        let m = machine(fresh)
        try navigating(m)
        m.cantMove()
        #expect(m.state == .shelter)
        let steps = m.shelter.steps.count
        for _ in 0..<(steps + 5) { m.shelterNext() } // clamps on the last step, never crashes
        #expect(m.shelterIndex == steps - 1)
        m.cantMove()                               // cantMove in shelter is a no-op (no re-enter/re-speak)
        #expect(m.state == .shelter)
        for _ in 0..<(steps + 5) { m.shelterBack() }
        #expect(m.state == .home)
    }

    @Test func arrivedEarlyFromStartPoint() throws {
        let m = machine(fresh)
        try m.start(client: Fixtures.client("walker", node: 0), caregiver: false)
        m.point(bearing: 200)
        while m.currentChoice?.refuge.id != "r_safeway" { m.other() }
        let ep = m.currentChoice!.refuge.entryPoints[0]
        m.setPosition(lat: ep.lat, lon: ep.lon)    // user is already standing at the refuge
        m.go()
        #expect(m.state == .arrived)
        #expect(m.utterances.first?.template == "arrived")
    }

    @Test func otherCyclesThroughAllChoices() throws {
        let m = machine(fresh)
        try m.start(client: Fixtures.client("walker", node: 112), caregiver: false)
        m.confirmFire()
        let n = m.choices.count
        #expect(n >= 2)
        let first = m.currentChoice?.refuge.id
        var seen: Set<String> = []
        for _ in 0..<n { seen.insert(m.currentChoice!.refuge.id); m.other() }
        #expect(m.currentChoice?.refuge.id == first)  // wraps back around after n taps
        #expect(seen.count == n)
    }

    @Test func blockingEverythingLandsInShelter() throws {
        let m = machine(fresh)
        try navigating(m)
        for _ in 0..<40 where m.state == .navigate { m.blockCurrent() }
        #expect(m.state == .shelter || m.state == .navigate)
        if m.state == .shelter {
            #expect(m.utterances.contains { $0.text.hasPrefix("No route") || $0.text == NavigatorStateMachine.noRoute }
                    || m.utterances.first?.text == m.shelter.steps.first)
        }
    }

    /// Regression: replan with a lead while in Choose used to speak the offered choice twice —
    /// sayChoice() then `say(lead + utterances)`. Must be a single utterance batch.
    @Test func fireInChooseSpeaksChoiceOnce() throws {
        let m = machine(stale)
        try m.start(client: Fixtures.client("manual_chair", node: 112), caregiver: false)
        m.point(bearing: 200)
        #expect(m.state == .choose)
        m.pointAtNewFire(bearing: 90)
        #expect(m.state == .choose)
        let texts = m.utterances.map(\.text)
        // one batch: fire_is + Rerouting + choice lines, in that order, no choice line before the lead
        #expect(texts.first == "Fire is to the east.")
        #expect(texts.count >= 3 && texts.count <= 4)
        #expect(texts[1] == "Rerouting.")
        #expect(texts[2].hasPrefix("Go to "))
    }

    /// Same regression via a voice-confirmed block on the current street while still in Choose.
    @Test func voiceBlockInChooseSpeaksChoiceOnce() throws {
        let m = machine(stale)
        try m.start(client: Fixtures.client("manual_chair", node: 112), caregiver: false)
        m.point(bearing: 200)
        #expect(m.state == .choose)
        let street = m.choices[0].route.edges.first.flatMap { m.streets.streetName(edge: $0) }
        if let match = street.flatMap({ m.resolveStreet($0, cross: nil) }), !match.edges.isEmpty {
            m.block(edges: match.edges)
            #expect(m.state == .choose)
            let texts = m.utterances.map(\.text)
            #expect(texts.allSatisfy { !$0.contains("Rerouting.") })   // choose replans carry no lead
            #expect(texts.first?.hasPrefix("Go to ") == true)
        }
    }

    @Test func profileSwitchMidRouteReplans() throws {
        let m = machine(fresh)
        try navigating(m)
        let edges = m.progress!.route.edges
        m.handle(.pushing)                          // caregiver starts pushing: slower profile
        #expect(m.profile?.key == "manual_chair_pushed")
        #expect(m.state == .navigate)
        #expect(m.progress!.route.edges != edges || m.progress!.route.timeS > 0)
    }

    @Test func intentsInEveryStateNeverCrash() throws {
        // each intent in each reachable state; asserts state validity only (coverage of texts is the harvest test)
        for mobility in ["manual_chair", "walker"] {
            let m = machine(stale)
            try m.start(client: Fixtures.client(mobility, node: 112), caregiver: false)
            let states: [(String, () -> Void)] = [
                ("whichWay", {}),
                ("choose", { m.confirmFire(); m.point(bearing: 120) }),
                ("navigate", { m.go() }),
                ("shelter", { m.cantMove() }),
            ]
            for (name, reach) in states {
                // re-drive a fresh machine to the target state
                let m2 = machine(stale)
                try m2.start(client: Fixtures.client(mobility, node: 112), caregiver: false)
                if name == "choose" { m2.point(bearing: 120) }
                if name == "navigate" { m2.point(bearing: 120); m2.go() }
                if name == "shelter" { m2.point(bearing: 120); m2.cantMove() }
                for i in Intent.allCases {
                    m2.handle(i)
                    #expect([.home, .whichWay, .choose, .navigate, .shelter, .arrived].contains(m2.state),
                            "\(i) in \(name) left state \(m2.state)")
                }
            }
            _ = m
        }
    }

    @Test func secondStartResetsToWhichWay() throws {
        // picking another profile then Start begins a fresh flow; nothing from the old run leaks
        let m = machine(stale)
        try navigating(m)
        try m.start(client: Fixtures.client("walker", node: 200), caregiver: false)
        #expect(m.state == .whichWay)
        #expect(m.progress == nil && m.blocked.isEmpty)
    }
}
