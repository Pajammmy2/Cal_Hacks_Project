import Foundation
import Testing
@testable import EmberCore

@Suite struct RouterTests {
    let b = Fixtures.bundle

    func refugeAt(bearing: Double, from origin: Int, distM: Double = 1000) -> Refuge {
        let g = b.graph
        let lat0 = g.lat[origin], lon0 = g.lon[origin]
        let dlat = distM * cos(Py.radians(bearing)) / 111320.0
        let dlon = distM * sin(Py.radians(bearing)) / (111320.0 * cos(Py.radians(lat0)))
        return Refuge(id: "t", name: "t", centroid: [lon0 + dlon, lat0 + dlat], entryPoints: [], score: 50)
    }

    @Test func fireSideFilter30ExcludedAnd90Kept() {
        let fire = 45.0
        for o in [0, 112, 224] {
            #expect(!Router.fireSideOK(b.graph, origin: o, refuge: refugeAt(bearing: fire + 30, from: o), fireBearing: fire, perimeter: nil))
            #expect(!Router.fireSideOK(b.graph, origin: o, refuge: refugeAt(bearing: fire - 30, from: o), fireBearing: fire, perimeter: nil))
            #expect(Router.fireSideOK(b.graph, origin: o, refuge: refugeAt(bearing: fire + 90, from: o), fireBearing: fire, perimeter: nil))
            #expect(Router.fireSideOK(b.graph, origin: o, refuge: refugeAt(bearing: fire - 90, from: o), fireBearing: fire, perimeter: nil))
        }
        // wrap-around: fire at 350, refuge at 20 (30 off) excluded
        #expect(!Router.fireSideOK(b.graph, origin: 0, refuge: refugeAt(bearing: 20, from: 0), fireBearing: 350, perimeter: nil))
    }

    @Test func perimeterBuffer() {
        let r = refugeAt(bearing: 180, from: 0)
        let lon = r.centroidLon, lat = r.centroidLat, d = 0.003
        let poly = [[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d]]
        #expect(!Router.fireSideOK(b.graph, origin: 0, refuge: r, fireBearing: nil, perimeter: poly))
        let far = poly.map { [$0[0] + 0.05, $0[1]] }
        #expect(Router.fireSideOK(b.graph, origin: 0, refuge: r, fireBearing: nil, perimeter: far))
    }

    @Test func noChairRouteUsesAStepEdge() {
        let g = b.graph
        #expect(g.edges.contains { $0.steps }, "fixture has a flight of steps")
        var routes = 0
        for key in ["manual_chair", "manual_chair_pushed", "power_chair"] {
            let p = Fixtures.profile(key)
            for origin in stride(from: 0, to: g.nodes.count, by: 7) {
                for fb in [nil, 45.0, 225.0] as [Double?] {
                    for c in Router.choose(g, refuges: b.refuges, profile: p, origin: origin, fireBearing: fb) {
                        routes += 1
                        for (i, ei) in c.route.edges.enumerated() {
                            let e = g.edges[ei]
                            let grade = c.route.forward[i] ? e.gradePct : -e.gradePct
                            #expect(!e.steps)
                            #expect(e.curbCut != .no)
                            #expect(e.surface != "unpaved")
                            #expect(abs(grade) <= p.maxGrade)
                        }
                    }
                }
            }
        }
        #expect(routes > 500)
    }

    @Test func raisedKerbRules() {
        let raised = Edge(a: 0, b: 1, lengthM: 12, gradePct: 0, curbCut: .no)
        for key in ["manual_chair", "manual_chair_pushed", "power_chair"] {
            let p = Fixtures.profile(key)
            #expect(p.edgeCost(raised, forward: true) == .infinity)
            let ok = p.edgeCost(Edge(a: 0, b: 1, lengthM: 12, gradePct: 0, curbCut: .yes), forward: true)
            let unknown = p.edgeCost(Edge(a: 0, b: 1, lengthM: 12, gradePct: 0, curbCut: .unknown), forward: true)
            #expect(abs(unknown - 3 * ok) < 1e-9)
        }
        let w = Fixtures.profile("walker")
        #expect(abs(w.edgeCost(raised, forward: true) - 12 / 0.6 * 2) < 1e-9)
        #expect(abs(w.edgeCost(Edge(a: 0, b: 1, lengthM: 12, gradePct: 0, curbCut: .unknown), forward: true) - 12 / 0.6) < 1e-9)
    }

    @Test func powerChairRangeLimitsPathLength() {
        let g = b.graph
        let p = Fixtures.profile("power_chair", battery: 5)   // 1 km
        #expect(p.rangeM == 1000)
        for origin in stride(from: 0, to: 225, by: 11) {
            for c in Router.choose(g, refuges: b.refuges, profile: p, origin: origin) {
                #expect(c.route.lengthM <= 1000)
            }
        }
    }

    @Test func bedboundNeverRoutes() {
        #expect(Router.choose(b.graph, refuges: b.refuges, profile: Fixtures.profile("bedbound"), origin: 0).isEmpty)
    }

    @Test func blockedReplanGivesDifferentRouteOrNoRouteWithinOneSecond() throws {
        var replans = 0, noRoutes = 0
        for origin in stride(from: 0, to: 225, by: 13) {
            let m = NavigatorStateMachine(bundle: b)
            m.clock = { Timestamps.parse("2026-10-23T13:00:00Z")! }
            try m.start(client: Fixtures.client("manual_chair", node: origin), caregiver: false)
            m.confirmFire()
            guard m.state == .choose else { #expect(m.state == .shelter); continue }
            m.go()
            guard m.state == .navigate, let before = m.progress?.route else { continue }
            if before.edges.isEmpty { continue }
            let t0 = Date()
            m.blockCurrent()
            let dt = Date().timeIntervalSince(t0)
            #expect(dt < 1.0)
            if m.state == .navigate {
                let after = m.progress!.route
                #expect(after.edges != before.edges)
                #expect(!after.edges.contains(before.edges[0]))
                #expect(m.utterances.first?.text == "Rerouting.")
                replans += 1
            } else {
                #expect(m.state == .shelter)
                #expect(m.utterances.first?.text == NavigatorStateMachine.noRoute)
                noRoutes += 1
            }
        }
        #expect(replans >= 5)
    }

    @Test func repeatedBlockingEndsInShelter() throws {
        let m = NavigatorStateMachine(bundle: b)
        m.clock = { Timestamps.parse("2026-10-23T13:00:00Z")! }
        try m.start(client: Fixtures.client("manual_chair", node: 0), caregiver: false)
        m.point(bearing: 45)
        m.go()
        var n = 0
        while m.state == .navigate && n < 2000 {
            m.blockCurrent()
            n += 1
        }
        #expect(m.state == .shelter)
        #expect(m.utterances.map(\.text) == [NavigatorStateMachine.noRoute, "Go to the back bedroom."])
    }

    @Test func syntheticTurnCues() throws {
        // A straight line, a slight right, a sharp left and an unnamed footway, on a tiny graph.
        func node(_ i: Int, _ dn: Double, _ de: Double) -> Node {
            Node(id: i, lat: 39.75 + dn / 111320.0, lon: -121.63 + de / (111320.0 * cos(Py.radians(39.75))), elev: 0)
        }
        let nodes = [node(0, 0, 0), node(1, 100, 0), node(2, 200, 0), node(3, 260, 60), node(4, 230, 20), node(5, 310, 20)]
        let edges = [Edge(a: 0, b: 1, lengthM: 100, gradePct: -5, name: "Clark Rd"),
                     Edge(a: 1, b: 2, lengthM: 100, gradePct: -5, name: "Clark Rd"),
                     Edge(a: 2, b: 3, lengthM: 90, gradePct: 0, name: "Pearson Rd"),
                     Edge(a: 3, b: 4, lengthM: 55, gradePct: 0, name: "Elm St"),
                     Edge(a: 4, b: 5, lengthM: 80, gradePct: 0, roadClass: "footway")]
        let g = Graph(GraphFile(nodes: nodes, edges: edges))
        let route = Route(nodes: [0, 1, 2, 3, 4, 5], edges: [0, 1, 2, 3, 4], forward: [true, true, true, true, true],
                          coords: [], lengthM: 425, timeS: 300, minutes: 5)
        let texts = Cues(graph: g, config: Fixtures.config).buildCues(route, refugeName: "the Safeway lot").map(\.text)
        #expect(texts == ["Start on Clark Rd. Go north.", "Keep going on Clark Rd for 200 meters.", "Downhill for 200 meters.",
                          "Turn slight right onto Pearson Rd.", "Keep going on Pearson Rd for 90 meters.",
                          "Turn sharp left onto Elm St.", "Keep going on Elm St for 60 meters.",
                          "Turn right onto the path.", "Keep going on the path for 80 meters.",
                          "Arrive at the Safeway lot."])
    }

    @Test func graphLoadsFast() throws {
        let t0 = Date()
        _ = try Graph(contentsOf: Fixtures.fakeDir.appendingPathComponent("graph.json"))
        #expect(Date().timeIntervalSince(t0) < 2.0)
    }

    func midpoint(_ ei: Int) -> (Double, Double) {
        let e = b.graph.edges[ei]
        return ((b.graph.lat[e.a] + b.graph.lat[e.b]) / 2.0, (b.graph.lon[e.a] + b.graph.lon[e.b]) / 2.0)
    }

    @Test func wedgeBlocksEdgesTowardTheFireOnly() {
        let g = b.graph
        let o = 112
        let lat = g.lat[o], lon = g.lon[o]
        for fire in [0.0, 90.0, 180.0, 270.0] {
            let w = Router.wedgeBlockedEdges(g, lat: lat, lon: lon, bearing: fire)
            #expect(!w.isEmpty)
            for a in g.adj[o] {
                #expect(w.contains(a.edge) == (Geo.angdiff(g.edgeBearing(a.edge, a.forward), fire) <= Router.wedgeHalfAngle))
            }
            for ei in 0..<g.edges.count {
                let (mlat, mlon) = midpoint(ei)
                let inside = Geo.haversineM(lat, lon, mlat, mlon) <= Router.wedgeRadiusM
                    && Geo.angdiff(Geo.bearingDeg(lat, lon, mlat, mlon), fire) <= Router.wedgeHalfAngle
                #expect(w.contains(ei) == inside)
            }
        }
    }

    @Test func fireRerouteChoosesRefugesAwayFromTheBearing() {
        let g = b.graph
        let p = Fixtures.profile("manual_chair")
        let o = 112
        let lat = g.lat[o], lon = g.lon[o]
        for fire in [0.0, 90.0, 180.0, 270.0] {
            let w = Router.wedgeBlockedEdges(g, lat: lat, lon: lon, bearing: fire)
            let out = Router.choose(g, refuges: b.refuges, profile: p, origin: o, fireBearing: fire, blocked: w)
            #expect(!out.isEmpty)
            for c in out {
                #expect(Geo.angdiff(Geo.bearingDeg(lat, lon, c.refuge.centroidLat, c.refuge.centroidLon), fire) > Router.fireSideHalfAngle)
                #expect(w.isDisjoint(with: c.route.edges))
                #expect(Geo.angdiff(g.edgeBearing(c.route.edges[0], c.route.forward[0]), fire) > Router.wedgeHalfAngle)
            }
        }
    }

    @Test func preferHeadingReordersOnlySimilarRoutes() {
        let g = b.graph
        let p = Fixtures.profile("manual_chair")
        var changed = 0
        for origin in stride(from: 0, to: g.nodes.count, by: 5) {
            guard let first = Router.choose(g, refuges: b.refuges, profile: p, origin: origin).first?.route else { continue }
            let heading = g.edgeBearing(first.edges[0], first.forward[0])
            let blocked: Set<Int> = [first.edges[0]]
            let plain = Router.choose(g, refuges: b.refuges, profile: p, origin: origin, blocked: blocked)
            let pref = Router.choose(g, refuges: b.refuges, profile: p, origin: origin, blocked: blocked, prefer: heading)
            #expect(pref.map(\.refuge.id).sorted() == plain.map(\.refuge.id).sorted())
            guard let fastest = plain.first else { continue }
            let limit = fastest.route.timeS * Router.headingSimilarRatio
            func turn(_ c: Choice) -> Double { Geo.angdiff(Router.initialHeading(g, route: c.route)!, heading) }
            #expect(pref[0].route.timeS <= limit)
            #expect(turn(pref[0]) <= plain.filter { $0.route.timeS <= limit }.map(turn).min()!)
            if pref[0].refuge.id != fastest.refuge.id { changed += 1 }
        }
        #expect(changed > 0)
        #expect(Router.initialHeading(g, route: Route(nodes: [0], edges: [], forward: [], coords: [], lengthM: 0, timeS: 0, minutes: 0)) == nil)
    }
}
