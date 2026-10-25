import Foundation

/// Tracks GPS progress along a route and which cue group is current.
/// A group is the cues that share a start point (turn + keep + slope); "arrive" is its own group.
public struct RouteProgress: Sendable {
    public static let announceAheadM = 15.0
    public static let arriveAnnounceM = 60.0
    static let backtrackWindowM = 30.0

    public let route: Route
    public let cues: [Cue]
    public let groups: [[Cue]]
    let cumM: [Double]          // distance from start to route node i (sum of edge length_m, like the cues)
    let edgeTimeS: [Double]
    public private(set) var progressM = 0.0
    public private(set) var edgeOffset = 0
    public private(set) var groupIndex = 0

    public init(route: Route, cues: [Cue], graph: Graph, profile: Profile) {
        self.route = route
        self.cues = cues
        var gs: [[Cue]] = []
        for c in cues {
            if let last = gs.last?.last, last.template != "arrive", c.template != "arrive",
               last.node == c.node, last.distanceM == c.distanceM, !["start", "turn", "turn_slight", "turn_sharp", "continue"].contains(c.template) {
                gs[gs.count - 1].append(c)
            } else {
                gs.append([c])
            }
        }
        groups = gs
        var cum = [0.0]
        var times: [Double] = []
        for (i, ei) in route.edges.enumerated() {
            let e = graph.edges[ei]
            cum.append(cum[cum.count - 1] + e.lengthM)
            let c = profile.edgeCost(e, forward: route.forward[i])
            times.append(c.isFinite ? c : 0)
        }
        cumM = cum
        edgeTimeS = times
    }

    public var totalM: Double { cumM.last ?? 0 }
    public var currentGroup: [Cue] { groups.isEmpty ? [] : groups[groupIndex] }
    public var currentEdge: Int? { route.edges.isEmpty ? nil : route.edges[min(edgeOffset, route.edges.count - 1)] }
    /// Node at the start of the current edge (where a re-plan starts without GPS).
    public var currentNode: Int { route.nodes[min(edgeOffset, max(0, route.nodes.count - 1))] }

    public var distanceToNextTurnM: Double? {
        guard groupIndex + 1 < groups.count, let c = groups[groupIndex + 1].first else { return nil }
        return max(0, c.distanceM - progressM)
    }

    public var remainingTimeS: Double {
        guard !route.edges.isEmpty else { return 0 }
        let i = min(edgeOffset, route.edges.count - 1)
        let len = cumM[i + 1] - cumM[i]
        let frac = len > 0 ? min(1, max(0, (progressM - cumM[i]) / len)) : 0
        return edgeTimeS[i] * (1 - frac) + edgeTimeS[(i + 1)...].reduce(0, +)
    }

    /// Update with a GPS fix. Returns true when a new cue group becomes current (speak it).
    @discardableResult
    public mutating func update(lat: Double, lon: Double, graph: Graph) -> Bool {
        guard !route.edges.isEmpty else { return false }
        var bestD = Double.infinity, bestAlong = progressM, bestI = edgeOffset
        for i in 0..<route.edges.count {
            if cumM[i + 1] < progressM - RouteProgress.backtrackWindowM { continue }
            let a = route.nodes[i], b = route.nodes[i + 1]
            let (d, t) = Geo.distanceToSegmentM(lat, lon, graph.lat[a], graph.lon[a], graph.lat[b], graph.lon[b])
            if d < bestD {
                bestD = d
                bestAlong = cumM[i] + t * (cumM[i + 1] - cumM[i])
                bestI = i
            }
        }
        progressM = bestAlong
        edgeOffset = bestI
        return advanceGroups()
    }

    /// Route distance at which the next cue group is first spoken (nil when the current group is the last).
    public var nextAnnounceM: Double? {
        guard groupIndex + 1 < groups.count else { return nil }
        let next = groups[groupIndex + 1][0]
        let ahead = next.template == "arrive" ? RouteProgress.arriveAnnounceM : RouteProgress.announceAheadM
        return next.distanceM - ahead
    }

    /// The point `s` metres along the route (clamped to the route's ends).
    public func point(atM s: Double, graph: Graph) -> (lat: Double, lon: Double) {
        let n = route.nodes
        guard n.count > 1 else { return (graph.lat[n[0]], graph.lon[n[0]]) }
        if s <= 0 { return (graph.lat[n[0]], graph.lon[n[0]]) }
        for i in 0..<(n.count - 1) where s <= cumM[i + 1] {
            let len = cumM[i + 1] - cumM[i]
            let t = len > 0 ? (s - cumM[i]) / len : 0
            let a = n[i], b = n[i + 1]
            return (graph.lat[a] + t * (graph.lat[b] - graph.lat[a]), graph.lon[a] + t * (graph.lon[b] - graph.lon[a]))
        }
        return (graph.lat[n[n.count - 1]], graph.lon[n[n.count - 1]])
    }

    mutating func advanceGroups() -> Bool {
        var g = groupIndex
        while g + 1 < groups.count {
            let next = groups[g + 1][0]
            let ahead = next.template == "arrive" ? RouteProgress.arriveAnnounceM : RouteProgress.announceAheadM
            if next.distanceM - ahead <= progressM { g += 1 } else { break }
        }
        if g != groupIndex { groupIndex = g; return true }
        return false
    }
}
