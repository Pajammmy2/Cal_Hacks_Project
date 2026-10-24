import Foundation
import Testing
@testable import EmberCore

@Suite struct StateMachineTests {
    let fresh = Timestamps.parse("2026-10-23T13:00:00Z")!   // fixture fire data is 1 h old
    let stale = Timestamps.parse("2026-10-23T19:00:00Z")!   // 7 h old

    func machine(_ now: Date) -> NavigatorStateMachine {
        let m = NavigatorStateMachine(bundle: Fixtures.bundle)
        m.clock = { now }
        return m
    }

    @Test func bedboundAlwaysShelter() throws {
        let m = machine(fresh)
        try m.start(client: Fixtures.client("bedbound"), caregiver: true)
        #expect(m.state == .shelter)
        #expect(m.shelter.room == "back bedroom")
        #expect(m.utterances.map(\.text) == ["Go to the back bedroom."])
        m.confirmFire(); m.go()
        #expect(m.state == .shelter)
    }

    @Test func freshFireDataAsksToConfirmDirection() throws {
        let m = machine(fresh)
        try m.start(client: Fixtures.client("manual_chair", node: 112), caregiver: false)
        #expect(m.state == .whichWay)
        #expect(m.fireIsFresh)
        #expect(m.utterances.map(\.text) == ["Fire is to the northeast. OK?"])   // wind from 45 deg, no perimeter
        m.confirmFire()
        #expect(m.state == .choose)
        #expect(m.fireBearing == 45)
        let a = try #require(m.currentChoice), b = try #require(m.alternateChoice)
        #expect(m.utterances.map(\.text) == ["Go to \(a.refuge.name). \(a.route.minutes) minutes.", "Or \(b.refuge.name). \(b.route.minutes) minutes."])
    }

    @Test func staleFireDataAsksToPoint() throws {
        let m = machine(stale)
        try m.start(client: Fixtures.client("walker", node: 112), caregiver: false)
        #expect(m.state == .whichWay)
        #expect(!m.fireIsFresh)
        #expect(m.utterances.map(\.text) == ["Point the phone at the smoke and tap."])
        m.confirmFire()                       // OK is not available with stale data
        #expect(m.state == .whichWay)
        m.point(bearing: 270)
        #expect(m.state == .choose)
        #expect(m.fireBearing == 270)
    }

    @Test func chooseOtherGoNavigateArriveDone() throws {
        let m = machine(fresh)
        try m.start(client: Fixtures.client("manual_chair", node: 0), caregiver: false)
        m.point(bearing: 200)
        let first = try #require(m.currentChoice)
        m.other()
        #expect(m.currentChoice?.refuge.id != first.refuge.id)
        m.go()
        #expect(m.state == .navigate)
        let c = try #require(m.currentChoice)
        #expect(m.utterances.first?.template == "start")
        // Walk the route node by node: cues advance, then arrival within 25 m.
        var spoken: [String] = m.utterances.map(\.text)
        var last = m.serial
        for n in c.route.nodes {
            m.updatePosition(lat: Fixtures.bundle.graph.lat[n], lon: Fixtures.bundle.graph.lon[n])
            if m.serial != last { spoken += m.utterances.map(\.text); last = m.serial }
            if m.state == .arrived { break }
        }
        #expect(m.state == .arrived)
        let key = c.refuge.isBuilding ? "arrived_building" : "arrived"
        #expect(m.utterances.first?.template == key)
        #expect(m.utterances.first?.text == Fixtures.config.template(key, ["refuge": c.refuge.name]))
        let cueTexts = Cues(graph: Fixtures.bundle.graph, config: Fixtures.config).buildCues(c.route, refugeName: c.refuge.name)
            .filter { $0.template != "arrive" }.map(\.text)
        for t in cueTexts { #expect(spoken.contains(t), "\(t) spoken") }
        m.done()
        #expect(m.state == .home)
    }

    @Test func arrivedTextForLot() throws {
        let m = machine(fresh)
        try m.start(client: Fixtures.client("walker", node: 0), caregiver: false)
        m.point(bearing: 200)
        while m.currentChoice?.refuge.id != "r_safeway" { m.other() }
        m.go()
        let ep = m.currentChoice!.refuge.entryPoints[0]
        m.updatePosition(lat: ep.lat + 20 / 111320.0, lon: ep.lon)   // 20 m away
        #expect(m.state == .arrived)
        #expect(m.utterances.map(\.text) == ["You are at the Safeway lot. Stay in the middle, away from the cars. Keep the phone on."])
    }

    @Test func cantMoveFromChooseAndNavigate() throws {
        let m = machine(fresh)
        try m.start(client: Fixtures.client("manual_chair", node: 112), caregiver: false)
        m.confirmFire()
        #expect(m.state == .choose)
        m.cantMove()
        #expect(m.state == .shelter)
        try m.start(client: Fixtures.client("manual_chair", node: 112), caregiver: false)
        m.confirmFire(); m.go()
        #expect(m.state == .navigate)
        m.handle(.cantMove)
        #expect(m.state == .shelter)
    }

    @Test func shelterNextRepeatBack() throws {
        let m = machine(fresh)
        try m.start(client: Fixtures.client("bedbound"), caregiver: false)
        m.shelterNext()
        #expect(m.utterances.map(\.text) == ["Close every window and door. Close the vents."])
        let s = m.serial
        m.repeatCurrent()
        #expect(m.serial == s + 1 && m.utterances.map(\.text) == ["Close every window and door. Close the vents."])
        for _ in 0..<10 { m.shelterNext() }
        #expect(m.shelterStep == "Call 911. Say: I am in the back bedroom.")
        for _ in 0..<5 { m.shelterBack() }
        #expect(m.shelterIndex == 0 && m.state == .shelter)
        m.shelterBack()
        #expect(m.state == .home)
    }

    @Test func caregiverModeUsesPushedProfileForManualChairOnly() throws {
        let m = machine(fresh)
        try m.start(client: Fixtures.client("manual_chair"), caregiver: true)
        #expect(m.profile?.key == "manual_chair_pushed")
        try m.start(client: Fixtures.client("manual_chair"), caregiver: false)
        #expect(m.profile?.key == "manual_chair")
        try m.start(client: Fixtures.client("power_chair"), caregiver: true)
        #expect(m.profile?.key == "power_chair")
        try m.start(client: Fixtures.client("cane"), caregiver: true)
        #expect(m.profile?.key == "walker")
        try m.start(client: Fixtures.client("manual_chair", node: 112), caregiver: false)
        m.confirmFire(); m.go()
        m.handle(.pushing)
        #expect(m.profile?.key == "manual_chair_pushed")
        #expect(m.state == .navigate)
        #expect(m.utterances.first?.text == "Switching to pushed chair.")
    }

    @Test func blockedStaysInNavigateWithNewRoute() throws {
        let m = machine(fresh)
        try m.start(client: Fixtures.client("manual_chair", node: 112), caregiver: false)
        m.confirmFire(); m.go()
        let before = m.progress!.route.edges
        m.handle(.blocked)
        #expect(m.state == .navigate)
        #expect(m.blocked == [before[0]])
        #expect(m.progress!.route.edges != before)
        #expect(m.utterances.first?.text == "Rerouting.")
    }

    @Test func voiceIntentsSpeakFixedTemplates() throws {
        let m = machine(fresh)
        try m.start(client: Fixtures.client("manual_chair", node: 112), caregiver: false)
        m.confirmFire(); m.go()
        m.handle(.whereAmI)
        #expect(m.utterances.first?.template == "where")
        #expect(m.utterances.first?.text.hasPrefix("You are on ") == true)
        m.handle(.howLong)
        #expect(m.utterances.first?.text.hasSuffix(" minutes to go.") == true)
        m.handle(.whichWay)
        #expect(m.utterances.first?.text.hasPrefix("Go ") == true)
        m.handle(.stop)
        #expect(m.stopped)
        #expect(m.utterances.first?.text == "Stopped. Speak or tap a button when you are ready.")
        m.handle(.repeat)
        #expect(!m.stopped)
    }

    @Test func homeShowsFireDataAge() {
        let t = Fixtures.bundle.fireDataTimestamp!
        #expect(Timestamps.ageText(Timestamps.parse("2026-10-23T15:00:00Z")!.timeIntervalSince(t)) == "3 h ago")
    }

    func bearingTo(_ m: NavigatorStateMachine, _ r: Refuge, from node: Int) -> Double {
        let g = m.graph
        return Geo.bearingDeg(g.lat[node], g.lon[node], r.centroidLat, r.centroidLon)
    }

    @Test func fireAheadClosesTheWedgeAndTurnsAway() throws {
        let m = machine(stale)
        try m.start(client: Fixtures.client("manual_chair", node: 112), caregiver: false)
        m.point(bearing: 200); m.go()
        let heading = try #require(m.travelHeading)
        let before = m.progress!.route.edges
        m.handle(.fire)                      // no compass: the route edge bearing is the fire bearing
        #expect(m.state == .navigate)
        #expect(m.fireBearing == heading)
        let wedge = Router.wedgeBlockedEdges(m.graph, lat: m.graph.lat[112], lon: m.graph.lon[112], bearing: heading)
        #expect(m.blocked == wedge.union([before[0]]))
        #expect(m.utterances.first?.text == "Fire ahead. Turning away from it.")
        #expect(m.utterances.count > 1)
        let c = try #require(m.currentChoice)
        #expect(Geo.angdiff(bearingTo(m, c.refuge, from: 112), heading) > Router.fireSideHalfAngle)
        #expect(wedge.isDisjoint(with: c.route.edges))
        #expect(m.alternateChoice != nil)    // B stays the fallback
    }

    @Test func fireAheadUsesTheCompassWhenAvailable() throws {
        let m = machine(stale)
        m.headingProvider = { 90 }
        try m.start(client: Fixtures.client("walker", node: 112), caregiver: false)
        m.point(bearing: 200); m.go()
        m.handle(.fire)
        #expect(m.fireBearing == 90)
        #expect(m.state == .navigate)
        #expect(Geo.angdiff(bearingTo(m, m.currentChoice!.refuge, from: 112), 90) > Router.fireSideHalfAngle)
    }

    @Test func fireOutsideNavigateAsksAgain() throws {
        let m = machine(stale)
        try m.start(client: Fixtures.client("walker", node: 112), caregiver: false)
        m.handle(.fire)
        #expect(m.state == .whichWay)
        #expect(m.utterances.map(\.text) == ["Say again?"])
    }

    @Test func pointAtNewFireUpdatesBearingAndReroutes() throws {
        let m = machine(stale)
        try m.start(client: Fixtures.client("manual_chair", node: 112), caregiver: false)
        m.point(bearing: 200); m.go()
        let before = m.progress!.route.edges
        let serial = m.serial
        m.pointAtNewFire(bearing: 45)
        #expect(m.state == .navigate)
        #expect(m.serial == serial + 1)
        #expect(m.fireBearing == 45)
        #expect(m.utterances.map(\.text).prefix(2) == ["Fire is to the northeast.", "Rerouting."])
        #expect(m.utterances.first?.template == "fire_is")
        #expect(m.progress!.route.edges != before)
        let c = try #require(m.currentChoice)
        #expect(Geo.angdiff(bearingTo(m, c.refuge, from: 112), 45) > Router.fireSideHalfAngle)
        let wedge = Router.wedgeBlockedEdges(m.graph, lat: m.graph.lat[112], lon: m.graph.lon[112], bearing: 45)
        #expect(m.blocked.isSuperset(of: wedge))
        #expect(wedge.isDisjoint(with: c.route.edges))
        // before Navigate it is the WhichWay "Point"
        let w = machine(stale)
        try w.start(client: Fixtures.client("manual_chair", node: 112), caregiver: false)
        w.pointAtNewFire(bearing: 270)
        #expect(w.state == .choose && w.fireBearing == 270)
    }

    @Test func physicalBlockKeepsDirection() throws {
        // Node 60: the fastest detour after blocking the first edge doubles back; the direction rule keeps going.
        let m = machine(stale)
        let g = Fixtures.bundle.graph
        try m.start(client: Fixtures.client("manual_chair", node: 60), caregiver: false)
        m.point(bearing: 270)
        // pick a refuge whose first edge heads east so the detour choice is meaningful
        let p = Fixtures.profile("manual_chair")
        let base = Router.choose(g, refuges: Fixtures.bundle.refuges, profile: p, origin: 60)
        let first = try #require(base.first)
        while m.currentChoice?.refuge.id != first.refuge.id { m.other() }
        m.go()
        let heading = try #require(m.travelHeading)
        m.handle(.blocked)
        #expect(m.state == .navigate)
        #expect(m.fireBearing == 270)                    // a physical block does not move the fire
        #expect(m.utterances.first?.text == "Rerouting.")
        let plain = Router.choose(g, refuges: Fixtures.bundle.refuges, profile: p, origin: 60, fireBearing: 270, blocked: m.blocked)
        let want = Router.preferHeading(g, plain, heading: heading)
        #expect(m.choices.map(\.refuge.id) == want.map(\.refuge.id))
        let limit = plain[0].route.timeS * Router.headingSimilarRatio
        func turn(_ c: Choice) -> Double { Geo.angdiff(Router.initialHeading(g, route: c.route)!, heading) }
        #expect(turn(m.currentChoice!) <= plain.filter { $0.route.timeS <= limit }.map(turn).min()!)
    }
}
