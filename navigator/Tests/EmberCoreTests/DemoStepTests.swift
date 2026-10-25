import Foundation
import Testing
@testable import EmberCore

/// Settings → "Demo: step through route": each tap is a GPS fix at the point where the next cue is spoken; the last
/// one lands on the route's final node (the entry point), never the refuge centroid.
@Suite struct DemoStepTests {
    let fresh = Timestamps.parse("2026-10-23T13:00:00Z")!

    func navigating(bundle: EmberBundle = Fixtures.bundle, client: ClientProfile? = nil) throws -> NavigatorStateMachine {
        let m = NavigatorStateMachine(bundle: bundle)
        m.clock = { fresh }
        let harold = client ?? Fixtures.client("power_chair", devices: [ClientDevice(kind: "oxygen", hours: 4)], node: 112)
        try m.start(client: harold, caregiver: false)
        m.confirmFire()
        #expect(m.state == .choose)
        m.go()
        #expect(m.state == .navigate)
        m.demoStepping = true
        return m
    }

    /// Steps until Arrived; returns the group index after each step. Every step before the last must speak exactly
    /// one new group (merges only when two groups announce within the same lookahead — same as GPS).
    @discardableResult
    func stepToArrived(_ m: NavigatorStateMachine, file: String = #filePath, line: Int = #line) throws -> [Int] {
        var trail: [Int] = []
        var last = try #require(m.progress).groupIndex
        let groups = try #require(m.progress).groups.count
        while m.state == .navigate, trail.count < groups + 2 {
            let serial = m.serial
            #expect(m.demoStep())
            if m.state == .navigate {
                let g = try #require(m.progress).groupIndex
                #expect(g == last + 1, "step \(trail.count + 1) spoke group \(g), expected \(last + 1)")
                #expect(m.serial > serial, "a new cue group must be spoken on every step")
                last = g
            }
            trail.append(m.progress?.groupIndex ?? last)
        }
        #expect(m.state == .arrived)
        return trail
    }

    @Test func stepsThroughTheWholeRouteToArrivedOneCueGroupPerTap() throws {
        let m = try navigating()
        let p = try #require(m.progress)
        let trail = try stepToArrived(m)
        // One tap per cue group after the first (already spoken at Go), plus one onto the entry point.
        #expect(trail.count == p.groups.count)
        #expect(trail.dropLast() == Array(1..<p.groups.count))
        #expect(!m.demoStep())
    }

    @Test func lastStepLandsOnTheRoutesFinalNodeNotTheCentroid() throws {
        let m = try navigating()
        let p = try #require(m.progress)
        let refuge = try #require(m.currentChoice).refuge
        let last = try #require(p.route.nodes.last)
        while m.state == .navigate, m.progress?.nextAnnounceM != nil { m.demoStep() }
        let t = try #require(m.demoNextPoint)
        #expect(t.lat == m.graph.lat[last] && t.lon == m.graph.lon[last])
        #expect(Router.arrived(lat: t.lat, lon: t.lon, refuge: refuge))
        m.demoStep()
        #expect(m.state == .arrived)
        let here = try #require(m.position)
        #expect(here.lat == t.lat && here.lon == t.lon)
    }

    /// 20 of 32 Paradise refuges have their centroid 27–97 m from every entry point: landing on the centroid never
    /// arrives, landing on the entry point always does.
    @Test func centroidSixtyMetresFromTheEntryPointIsNotArrival() {
        let entry = EntryPoint(node: 0, lat: 39.7600, lon: -121.6000)
        let dLat = 60.0 / 111_320.0
        let r = Refuge(id: "r_big", name: "the sports field on Dolores Drive", centroid: [entry.lon, entry.lat + dLat],
                       entryPoints: [entry], score: 50)
        #expect(!Router.arrived(lat: r.centroidLat, lon: r.centroidLon, refuge: r))
        #expect(Router.arrived(lat: entry.lat, lon: entry.lon, refuge: r))
    }

    /// Every bundle refuge: the graph node a route ends on is within the arrival radius of an entry point.
    @Test func everyRefugeEntryNodeIsWithinArrivalRadius() {
        let g = Fixtures.bundle.graph
        for r in Fixtures.bundle.refuges {
            let nodes = r.entryPoints.compactMap(\.node)
            #expect(!nodes.isEmpty, "\(r.id) has no routable entry point")
            for n in nodes {
                #expect(Router.arrived(lat: g.lat[n], lon: g.lon[n], refuge: r), "\(r.id): entry node \(n) is > \(Router.arrivalRadiusM) m from every entry point")
            }
        }
    }

    @Test func blockedMidwayThenNextContinuesOnTheNewRoute() throws {
        let m = try navigating()
        m.demoStep()
        m.demoStep()
        let before = try #require(m.progress)
        let stepped = try #require(m.position)
        m.blockCurrent()
        #expect(m.state == .navigate)
        let after = try #require(m.progress)
        #expect(after.route.edges != before.route.edges)
        let here = try #require(m.position)
        #expect(abs(here.lat - stepped.lat) < 1e-9 && abs(here.lon - stepped.lon) < 1e-9)
        try stepToArrived(m)
    }

    /// Owner's phone: after a rehearsal ended at the refuge, scanning again said the route was already done, because
    /// the stepped position was still the origin. A new start forgets a demo position (a real GPS fix is kept).
    @Test func newStartAfterADemoRunBeginsAtTheClientsHomeNotTheRefuge() throws {
        let m = try navigating()
        try stepToArrived(m)
        let g = Fixtures.bundle.graph
        let harold = Fixtures.client("power_chair", devices: [ClientDevice(kind: "oxygen", hours: 4)], node: 112)
        try m.start(client: harold, caregiver: false)
        #expect(m.originPoint?.lat == g.lat[112] && m.originPoint?.lon == g.lon[112])
        m.confirmFire(); m.go()
        #expect(m.state == .navigate)
        #expect((m.currentChoice?.route.timeS ?? 0) > 0)
        m.demoStepping = true
        try stepToArrived(m)
        m.demoStepping = false
        m.updatePosition(lat: g.lat[112], lon: g.lon[112])            // real fix after the toggle is off: kept
        try m.start(client: harold, caregiver: false)
        #expect(m.originPoint?.lat == g.lat[112])
    }

    @Test func gpsIsIgnoredWhileSteppingAndResumesWhenOff() throws {
        let m = try navigating()
        let start = try #require(m.progress).progressM
        let far = m.demoNextPoint!
        m.updatePosition(lat: far.lat, lon: far.lon)
        #expect(m.progress?.progressM == start)
        m.demoStepping = false
        m.updatePosition(lat: far.lat, lon: far.lon)
        #expect((m.progress?.progressM ?? 0) > start || m.state == .arrived)
    }

    /// Real Paradise bundle (not in the repo): EMBER_REAL_BUNDLE=/path/to/bundles/paradise swift test --filter Demo.
    /// Harold (power chair, 5974 Pentz Road) steps to Arrived one cue group per tap; every refuge's entry nodes arrive.
    @Test(.enabled(if: ProcessInfo.processInfo.environment["EMBER_REAL_BUNDLE"] != nil))
    func realBundleHaroldAndEveryRefuge() throws {
        let dir = URL(fileURLWithPath: ProcessInfo.processInfo.environment["EMBER_REAL_BUNDLE"]!)
        let bundle = try EmberBundle(dir: dir, sharedFallback: Fixtures.sharedDir)
        let g = bundle.graph
        for r in bundle.refuges {
            let nodes = r.entryPoints.compactMap(\.node)
            #expect(!nodes.isEmpty, "\(r.id) has no routable entry point")
            for n in nodes {
                #expect(Router.arrived(lat: g.lat[n], lon: g.lon[n], refuge: r), "\(r.id): entry node \(n) is > 25 m from every entry point")
            }
        }
        let harold = ClientProfile(id: "c_harold", name: "Harold Kim", mobility: "power_chair", transfer: nil,
                                   devices: [ClientDevice(kind: "oxygen", hours: 4)], home: ClientHome(),
                                   lat: 39.748562, lon: -121.615275, county: "Butte")   // plans/c_harold.json origin
        let m = try navigating(bundle: bundle, client: harold)
        let p = try #require(m.progress)
        let trail = try stepToArrived(m)
        #expect(trail.count == p.groups.count)
        print("REAL Harold: \(p.groups.count) cue groups, \(trail.count) taps, \(Int(p.route.lengthM)) m → \(m.arrivedRefuge?.name ?? "?")")
    }
}
