import Foundation

/// Resolves block_edge(street, cross_street?) to graph edge indices.
public struct StreetLookup: Sendable {
    public struct Match: Sendable, Equatable {
        public var edges: [Int]
        /// Street names as the graph spells them (used in the spoken read-back).
        public var street: String
        public var crossStreet: String?
    }

    static let abbr = ["road": "rd", "street": "st", "avenue": "ave", "drive": "dr", "lane": "ln", "court": "ct",
                       "boulevard": "blvd", "place": "pl", "way": "way", "circle": "cir", "parkway": "pkwy",
                       "highway": "hwy", "north": "n", "south": "s", "east": "e", "west": "w", "terrace": "ter",
                       "trail": "trl"]
    public static let nearbyM = 2000.0

    let graph: Graph
    let templates: TurnTemplates

    public init(graph: Graph, templates: TurnTemplates) { self.graph = graph; self.templates = templates }

    /// Same normalization as the engine's local geocoder.
    public static func norm(_ s: String) -> String {
        let cleaned = s.lowercased().unicodeScalars.map { CharacterSet.alphanumerics.contains($0) || $0 == "_" ? Character($0) : " " }
        return String(cleaned).split(separator: " ").map { abbr[String($0)] ?? String($0) }.joined(separator: " ")
    }

    func matches(_ edgeName: String?, _ query: String) -> Bool {
        guard let edgeName, !edgeName.isEmpty else { return false }
        let k = StreetLookup.norm(edgeName)
        if k == query { return true }
        // tolerate a missing suffix ("Clark" vs "Clark Rd")
        guard let kf = k.split(separator: " ").first, let qf = query.split(separator: " ").first, kf == qf else { return false }
        return k.contains(query) || query.contains(k)
    }

    /// Edges named `street` near the user. With a cross street: that street's edges touching the intersection
    /// closest to the user. Without: the next stretch of that street on the route ahead, else every edge of it
    /// within 2 km.
    public func resolve(street: String, crossStreet: String?, nearLat: Double, nearLon: Double,
                        routeAhead: [Int] = []) -> Match? {
        let q = StreetLookup.norm(street)
        guard !q.isEmpty else { return nil }
        let named = graph.edges.indices.filter { matches(graph.edges[$0].name, q) }
        guard let first = named.first else { return nil }
        let display = graph.edges[first].name ?? street

        if let cross = crossStreet, !cross.trimmingCharacters(in: .whitespaces).isEmpty {
            let cq = StreetLookup.norm(cross)
            let streetSet = Set(named)
            var bestNode: Int? = nil, bestD = Double.infinity
            var crossName: String? = nil
            for ei in named {
                let e = graph.edges[ei]
                for n in [e.a, e.b] {
                    guard let ce = graph.adj[n].first(where: { !streetSet.contains($0.edge) && matches(graph.edges[$0.edge].name, cq) }) else { continue }
                    let d = Geo.haversineM(nearLat, nearLon, graph.lat[n], graph.lon[n])
                    if d < bestD { bestD = d; bestNode = n; crossName = graph.edges[ce.edge].name }
                }
            }
            guard let node = bestNode else { return nil }
            let edges = graph.adj[node].map(\.edge).filter { streetSet.contains($0) }
            return Match(edges: edges.sorted(), street: graph.edges[edges[0]].name ?? display, crossStreet: crossName ?? cross)
        }

        var ahead: [Int] = []
        for ei in routeAhead {
            if matches(graph.edges[ei].name, q) { ahead.append(ei) } else if !ahead.isEmpty { break }
        }
        if !ahead.isEmpty { return Match(edges: ahead, street: graph.edges[ahead[0]].name ?? display, crossStreet: nil) }

        let near = named.filter { ei in
            let e = graph.edges[ei]
            return min(Geo.haversineM(nearLat, nearLon, graph.lat[e.a], graph.lon[e.a]),
                       Geo.haversineM(nearLat, nearLon, graph.lat[e.b], graph.lon[e.b])) <= StreetLookup.nearbyM
        }
        guard !near.isEmpty else { return nil }
        return Match(edges: near, street: graph.edges[near[0]].name ?? display, crossStreet: nil)
    }

    /// The street a user is on (for "You are on {street}."), using the cue display name.
    public func streetName(edge: Int) -> String { Cues.displayName(graph.edges[edge], templates) }
}
