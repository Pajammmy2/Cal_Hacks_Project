import Foundation

/// Port of router.Graph: adjacency arrays and a ~200 m grid for snapping.
public final class Graph: @unchecked Sendable {
    public struct Adj: Sendable { public let edge: Int; public let nb: Int; public let forward: Bool }

    public let nodes: [Node]
    public let edges: [Edge]
    public let lat: [Double]
    public let lon: [Double]
    public let adj: [[Adj]]
    public let degree: [Int]
    let cell = 0.002
    private var grid: [GridKey: [Int]] = [:]

    struct GridKey: Hashable { let y: Int; let x: Int }

    public init(_ file: GraphFile) {
        nodes = file.nodes
        edges = file.edges
        lat = file.nodes.map(\.lat)
        lon = file.nodes.map(\.lon)
        var a = [[Adj]](repeating: [], count: file.nodes.count)
        for (i, e) in file.edges.enumerated() {
            a[e.a].append(Adj(edge: i, nb: e.b, forward: true))
            a[e.b].append(Adj(edge: i, nb: e.a, forward: false))
        }
        adj = a
        degree = a.map(\.count)
        for i in 0..<file.nodes.count {
            grid[key(lat[i], lon[i]), default: []].append(i)
        }
    }

    public convenience init(contentsOf url: URL) throws {
        self.init(try GraphFile.parse(Data(contentsOf: url)))
    }

    func key(_ lat: Double, _ lon: Double) -> GridKey {
        GridKey(y: Int(floor(lat / cell)), x: Int(floor(lon / cell)))
    }

    /// Nearest node, searching outward ring by ring. `usable` filters candidates.
    public func snap(_ qlat: Double, _ qlon: Double, usable: ((Int) -> Bool)? = nil) -> (node: Int?, distance: Double) {
        let k = key(qlat, qlon)
        var best: Int? = nil
        var bestD = Double.infinity
        for r in 0..<60 {
            for dy in -r...r {
                for dx in -r...r {
                    if max(abs(dy), abs(dx)) != r { continue }
                    guard let cellNodes = grid[GridKey(y: k.y + dy, x: k.x + dx)] else { continue }
                    for i in cellNodes {
                        if let usable, !usable(i) { continue }
                        let d = Geo.haversineM(qlat, qlon, lat[i], lon[i])
                        if d < bestD { best = i; bestD = d }
                    }
                }
            }
            let coveredM = Double(r) * cell * 111000.0 * cos(Py.radians(qlat))
            if best != nil, coveredM >= bestD { break }
        }
        return (best, bestD)
    }

    public func edgeBearing(_ edgeIndex: Int, _ forward: Bool) -> Double {
        let e = edges[edgeIndex]
        let (a, b) = forward ? (e.a, e.b) : (e.b, e.a)
        return Geo.bearingDeg(lat[a], lon[a], lat[b], lon[b])
    }

    /// Nearest edge to a point within `maxM` (for feed closures and GPS progress). Searches nodes in nearby cells.
    public func nearestEdge(_ qlat: Double, _ qlon: Double, maxM: Double = 100,
                            filter: ((Int) -> Bool)? = nil) -> (edge: Int, distance: Double)? {
        let k = key(qlat, qlon)
        let rings = max(1, Int(ceil(maxM / (cell * 111000.0 * cos(Py.radians(qlat)))))) + 1
        var seen = Set<Int>()
        var best: (Int, Double)? = nil
        for dy in -rings...rings {
            for dx in -rings...rings {
                for n in grid[GridKey(y: k.y + dy, x: k.x + dx)] ?? [] {
                    for a in adj[n] where seen.insert(a.edge).inserted {
                        if let filter, !filter(a.edge) { continue }
                        let e = edges[a.edge]
                        let d = Geo.distanceToSegmentM(qlat, qlon, lat[e.a], lon[e.a], lat[e.b], lon[e.b]).d
                        if d <= maxM, best == nil || d < best!.1 { best = (a.edge, d) }
                    }
                }
            }
        }
        return best.map { (edge: $0.0, distance: $0.1) }
    }
}
