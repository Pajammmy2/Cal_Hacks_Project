import Foundation

/// Port of engine/ember_engine/core/router.py. Costs, heap order and tie-breaks match Python exactly
/// because cue strings (and so the pre-generated Cartesia clips) depend on the chosen route.
public struct Profile: Sendable, Equatable {
    public let key: String
    public let label: String
    public let maxGrade: Double
    public let speedFlat: Double
    public let uphillSlowdown: Bool
    public let forbidSteps: String
    public let forbidUnpaved: Bool
    public let penalize: [String]
    public let penalizeX2: [String]
    public let impassable: [String]
    public let shelterOnly: Bool
    public let rangeM: Double

    public init(_ key: String, batteryPct: Double = 100.0, config: SharedConfig) throws {
        guard let spec = config.profiles[key] else { throw EmberError.missing("profile \(key)") }
        self.init(key: key, spec: spec, batteryPct: batteryPct)
    }

    public init(key: String, spec: ProfileSpec, batteryPct: Double = 100.0) {
        self.key = key
        label = spec.label
        maxGrade = spec.maxGradePct
        speedFlat = spec.speedFlatMps
        uphillSlowdown = spec.uphillSlowdown
        forbidSteps = spec.forbidSteps
        forbidUnpaved = spec.forbidUnpaved
        penalize = spec.penalizeX3
        penalizeX2 = spec.penalizeX2 ?? []
        impassable = spec.impassable ?? []
        shelterOnly = spec.shelterOnly
        if spec.batteryRange {
            rangeM = max(0.0, batteryPct) / 100.0 * (spec.fullRangeM ?? 0)
        } else {
            rangeM = .infinity
        }
    }

    /// Seconds to traverse e in the given direction, or +inf if impassable.
    public func edgeCost(_ e: Edge, forward: Bool) -> Double {
        if shelterOnly { return .infinity }
        let grade = forward ? e.gradePct : -e.gradePct
        if e.steps {
            if forbidSteps == "all" { return .infinity }
            if forbidSteps == "gt3" {
                if e.stepCount == nil || e.stepCount! > 3 { return .infinity }
            }
        }
        if forbidUnpaved && e.surface == "unpaved" { return .infinity }
        if abs(grade) > maxGrade { return .infinity }
        // raised kerb with no lowered/flush kerb at the crossing (graph build resolves that into curb_cut false)
        if impassable.contains("curb_cut_false") && e.curbCut == .no { return .infinity }
        var speed = speedFlat
        if uphillSlowdown {
            if grade > 0 {
                speed *= max(0.3, 1.0 - grade / 10.0)
            } else if grade < -6.0 {
                speed *= 0.8
            }
        }
        var penalty = 1.0
        for rule in penalize {
            if rule == "curb_cut_unknown" && e.curbCut == .unknown {
                penalty *= 3.0
            } else if rule == "no_sidewalk_primary_secondary" && (e.roadClass == "primary" || e.roadClass == "secondary") && !e.sidewalk {
                penalty *= 3.0
            } else if rule == "grade_gt_6" && abs(grade) > 6.0 {
                penalty *= 3.0
            }
        }
        for rule in penalizeX2 where rule == "curb_cut_false" && e.curbCut == .no {
            penalty *= 2.0
        }
        return e.lengthM / speed * penalty
    }
}

public struct Route: Sendable, Equatable {
    public var nodes: [Int]
    public var edges: [Int]
    public var forward: [Bool]
    public var coords: [[Double]]   // [lat, lon]
    public var lengthM: Double      // rounded to 0.1 like Python
    public var timeS: Double        // rounded to 0.1 like Python
    public var minutes: Int
}

public struct Choice: Sendable, Equatable {
    public var refuge: Refuge
    public var route: Route
}

public enum Router {
    public static let topN = 5
    public static let fireSideHalfAngle = 60.0
    public static let perimeterBufferM = 500.0
    public static let arrivalRadiusM = 25.0
    /// "Fire ahead": close every edge whose midpoint lies within wedgeRadiusM and within +-wedgeHalfAngle of the fire bearing.
    public static let wedgeHalfAngle = 60.0
    public static let wedgeRadiusM = 400.0
    /// Physical blockage: among routes within headingSimilarRatio of the fastest, prefer the one whose first
    /// headingWindowM heading is closest to the previous direction of travel.
    public static let headingWindowM = 200.0
    public static let headingSimilarRatio = 1.25

    /// Min-heap ordered like Python tuples (f, g, node).
    struct Heap {
        struct Item { let f: Double; let g: Double; let n: Int }
        var a: [Item] = []
        static func less(_ x: Item, _ y: Item) -> Bool {
            if x.f != y.f { return x.f < y.f }
            if x.g != y.g { return x.g < y.g }
            return x.n < y.n
        }
        var isEmpty: Bool { a.isEmpty }
        mutating func push(_ it: Item) {
            a.append(it)
            var i = a.count - 1
            while i > 0 {
                let p = (i - 1) / 2
                if Heap.less(a[i], a[p]) { a.swapAt(i, p); i = p } else { break }
            }
        }
        mutating func pop() -> Item {
            let top = a[0]
            let last = a.removeLast()
            if !a.isEmpty {
                a[0] = last
                var i = 0
                while true {
                    let l = 2 * i + 1, r = l + 1
                    var m = i
                    if l < a.count && Heap.less(a[l], a[m]) { m = l }
                    if r < a.count && Heap.less(a[r], a[m]) { m = r }
                    if m == i { break }
                    a.swapAt(i, m)
                    i = m
                }
            }
            return top
        }
    }

    /// A* from start to the nearest (by cost) node in goals.
    /// Fastest route to the nearest goal. Battery range (power chair): if the fastest route is longer than the
    /// range, fall back to the shortest passable route, which is within range whenever any route is.
    public static func astar(_ g: Graph, _ profile: Profile, start: Int?, goals goalList: [Int],
                             blocked: Set<Int> = []) -> Route? {
        var route = search(g, profile, start: start, goals: goalList, blocked: blocked, byLength: false)
        if let r = route, r.lengthM > profile.rangeM {
            route = search(g, profile, start: start, goals: goalList, blocked: blocked, byLength: true)
        }
        return route
    }

    static func search(_ g: Graph, _ profile: Profile, start: Int?, goals goalList: [Int],
                       blocked: Set<Int>, byLength: Bool) -> Route? {
        let goals = Set(goalList)
        guard let start, !goals.isEmpty, !profile.shelterOnly else { return nil }
        let gl = goals.map { (g.lat[$0], g.lon[$0]) }
        let hDiv = byLength ? 1.0 : profile.speedFlat
        func h(_ n: Int) -> Double {
            var d = Double.infinity
            for (la, lo) in gl { d = min(d, Geo.haversineM(g.lat[n], g.lon[n], la, lo)) }
            return d / hDiv
        }
        let count = g.nodes.count
        var gKey = [Double](repeating: .infinity, count: count)
        var gTime = [Double](repeating: 0, count: count)
        var gLen = [Double](repeating: 0, count: count)
        var prev = [(n: Int, e: Int, fwd: Bool)?](repeating: nil, count: count)
        var closed = [Bool](repeating: false, count: count)
        gKey[start] = 0
        var heap = Heap()
        heap.push(.init(f: h(start), g: 0.0, n: start))
        while !heap.isEmpty {
            let it = heap.pop()
            let n = it.n
            if closed[n] { continue }
            closed[n] = true
            if goals.contains(n) { return buildRoute(g, prev, gTime, gLen, start: start, end: n) }
            for a in g.adj[n] {
                if blocked.contains(a.edge) || closed[a.nb] { continue }
                let e = g.edges[a.edge]
                let c = profile.edgeCost(e, forward: a.forward)
                if c == .infinity { continue }
                let nl = gLen[n] + e.lengthM
                if byLength && nl > profile.rangeM { continue }
                let ng = it.g + (byLength ? e.lengthM : c)
                if ng < gKey[a.nb] {
                    gKey[a.nb] = ng
                    gTime[a.nb] = gTime[n] + c
                    gLen[a.nb] = nl
                    prev[a.nb] = (n, a.edge, a.forward)
                    heap.push(.init(f: ng + h(a.nb), g: ng, n: a.nb))
                }
            }
        }
        return nil
    }

    static func buildRoute(_ g: Graph, _ prev: [(n: Int, e: Int, fwd: Bool)?], _ gCost: [Double], _ gLen: [Double],
                           start: Int, end: Int) -> Route {
        var nodes = [end], edges: [Int] = [], dirs: [Bool] = []
        var cur = end
        while cur != start, let p = prev[cur] {
            edges.append(p.e)
            dirs.append(p.fwd)
            nodes.append(p.n)
            cur = p.n
        }
        nodes.reverse(); edges.reverse(); dirs.reverse()
        let t = gCost[end]
        return Route(nodes: nodes, edges: edges, forward: dirs,
                     coords: nodes.map { [g.lat[$0], g.lon[$0]] },
                     lengthM: Py.round(gLen[end], 1), timeS: Py.round(t, 1),
                     minutes: t > 0 ? Int(ceil(t / 60.0)) : 0)
    }

    public static func fireSideOK(_ g: Graph, origin: Int, refuge: Refuge, fireBearing: Double?, perimeter: [[Double]]?) -> Bool {
        let clat = refuge.centroidLat, clon = refuge.centroidLon
        if let fireBearing {
            let b = Geo.bearingDeg(g.lat[origin], g.lon[origin], clat, clon)
            if Geo.angdiff(b, fireBearing) <= fireSideHalfAngle { return false }
        }
        if let perimeter, !perimeter.isEmpty {
            if Geo.pointInPolygon(clat, clon, perimeter) { return false }
            if Geo.distanceToPolygonEdgeM(clat, clon, perimeter) <= perimeterBufferM { return false }
        }
        return true
    }

    /// Edges whose midpoint is within radiusM of (lat, lon) and within +-halfAngle of `bearing` (the fire side).
    public static func wedgeBlockedEdges(_ g: Graph, lat: Double, lon: Double, bearing: Double,
                                         halfAngle: Double = wedgeHalfAngle, radiusM: Double = wedgeRadiusM) -> Set<Int> {
        var out = Set<Int>()
        for (i, e) in g.edges.enumerated() {
            let mlat = (g.lat[e.a] + g.lat[e.b]) / 2.0
            let mlon = (g.lon[e.a] + g.lon[e.b]) / 2.0
            if Geo.haversineM(lat, lon, mlat, mlon) > radiusM { continue }
            if Geo.angdiff(Geo.bearingDeg(lat, lon, mlat, mlon), bearing) <= halfAngle { out.insert(i) }
        }
        return out
    }

    /// Bearing from the route start to the first node at or beyond windowM along it (the last node if shorter).
    public static func initialHeading(_ g: Graph, route: Route, windowM: Double = headingWindowM) -> Double? {
        let nodes = route.nodes
        guard nodes.count >= 2 else { return nil }
        var cum = 0.0
        var end = nodes[nodes.count - 1]
        for (i, ei) in route.edges.enumerated() {
            cum += g.edges[ei].lengthM
            if cum >= windowM { end = nodes[i + 1]; break }
        }
        return Geo.bearingDeg(g.lat[nodes[0]], g.lon[nodes[0]], g.lat[end], g.lon[end])
    }

    /// Stable re-order: candidates within headingSimilarRatio of the fastest time come first, sorted by how close
    /// their initial heading is to `heading`; the rest keep their (time, -score) order.
    public static func preferHeading(_ g: Graph, _ candidates: [Choice], heading: Double?) -> [Choice] {
        guard let heading, let first = candidates.first else { return candidates }
        let limit = first.route.timeS * headingSimilarRatio
        func turn(_ c: Choice) -> Double {
            initialHeading(g, route: c.route).map { Geo.angdiff($0, heading) } ?? 180.0
        }
        let similar = candidates.enumerated().filter { $0.element.route.timeS <= limit }
            .sorted { a, b in
                let ta = turn(a.element), tb = turn(b.element)
                return ta != tb ? ta < tb : a.offset < b.offset
            }.map(\.element)
        let rest = candidates.filter { $0.route.timeS > limit }
        return similar + rest
    }

    /// Fire-side filter -> top N by score -> route each -> sort by (time, -score). Index 0 = A, 1 = B.
    /// `prefer` (a heading in degrees) applies preferHeading() to the sorted list (physical blockage re-plan).
    public static func choose(_ g: Graph, refuges: [Refuge], profile: Profile, origin: Int,
                              fireBearing: Double? = nil, perimeter: [[Double]]? = nil,
                              blocked: Set<Int> = [], topN: Int = topN, prefer: Double? = nil) -> [Choice] {
        if profile.shelterOnly { return [] }
        // Python's sort is stable; carry the original index as the final key.
        let allowed = refuges.enumerated()
            .filter { fireSideOK(g, origin: origin, refuge: $0.element, fireBearing: fireBearing, perimeter: perimeter) }
            .sorted { $0.element.score != $1.element.score ? -$0.element.score < -$1.element.score : $0.offset < $1.offset }
            .map(\.element)
        var out: [(Int, Choice)] = []
        for r in allowed.prefix(topN) {
            let goals = r.entryPoints.compactMap(\.node)
            if let route = astar(g, profile, start: origin, goals: goals, blocked: blocked) {
                out.append((out.count, Choice(refuge: r, route: route)))
            }
        }
        out.sort { x, y in
            if x.1.route.timeS != y.1.route.timeS { return x.1.route.timeS < y.1.route.timeS }
            if x.1.refuge.score != y.1.refuge.score { return -x.1.refuge.score < -y.1.refuge.score }
            return x.0 < y.0
        }
        return preferHeading(g, out.map(\.1), heading: prefer)
    }

    public static func arrived(lat: Double, lon: Double, refuge: Refuge) -> Bool {
        refuge.entryPoints.contains { Geo.haversineM(lat, lon, $0.lat, $0.lon) <= arrivalRadiusM }
    }

    /// Snap filter: only nodes with at least one passable edge for this profile.
    public static func usableOrigin(_ g: Graph, _ profile: Profile) -> (Int) -> Bool {
        { n in g.adj[n].contains { profile.edgeCost(g.edges[$0.edge], forward: $0.forward) < .infinity } }
    }
}
