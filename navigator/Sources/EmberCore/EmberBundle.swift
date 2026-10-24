import Foundation

/// A loaded county bundle (`bundles/<county>/`), graph in memory.
public final class EmberBundle: @unchecked Sendable {
    public let dir: URL
    public let manifest: Manifest?
    public let graph: Graph
    public let refuges: [Refuge]
    public let perimeters: PerimetersFile?
    public let wind: Wind?
    public let config: SharedConfig

    public var county: String { manifest?.county ?? dir.lastPathComponent }
    public var audioDir: URL { dir.appendingPathComponent("audio") }

    /// `sharedFallback` is used when the bundle has no `shared/` copy (the app ships shared/*.json as resources).
    public init(dir: URL, sharedFallback: URL? = nil) throws {
        self.dir = dir
        let dec = JSONDecoder()
        func read<T: Decodable>(_ name: String, _ type: T.Type) -> T? {
            guard let d = try? Data(contentsOf: dir.appendingPathComponent(name)) else { return nil }
            return try? dec.decode(type, from: d)
        }
        manifest = read("manifest.json", Manifest.self)
        let sharedDir = dir.appendingPathComponent("shared")
        if FileManager.default.fileExists(atPath: sharedDir.appendingPathComponent("profiles.json").path) {
            config = try SharedConfig.load(from: sharedDir)
        } else if let sharedFallback {
            config = try SharedConfig.load(from: sharedFallback)
        } else {
            throw EmberError.missing("shared/")
        }
        graph = try Graph(contentsOf: dir.appendingPathComponent("graph.json"))
        guard let rf = read("refuges.json", RefugesFile.self) else { throw EmberError.badBundle("refuges.json") }
        refuges = rf.refuges
        perimeters = read("perimeters.json", PerimetersFile.self)
        wind = read("wind.json", Wind.self)
    }

    /// True if the point is inside the manifest bbox (padded ~2 km). GPS outside the county is not used for routing.
    public func contains(lat: Double, lon: Double, padDeg: Double = 0.02) -> Bool {
        guard let b = manifest?.bbox, b.count == 4 else { return true }
        return lon >= b[0] - padDeg && lat >= b[1] - padDeg && lon <= b[2] + padDeg && lat <= b[3] + padDeg
    }

    public func refuge(_ id: String) -> Refuge? { refuges.first { $0.id == id } }

    public func thumbURL(_ r: Refuge) -> URL? {
        guard let t = r.thumb else { return nil }
        let u = dir.appendingPathComponent(t)
        return FileManager.default.fileExists(atPath: u.path) ? u : nil
    }

    public func plan(clientId: String) -> PlanFile? {
        let u = dir.appendingPathComponent("plans/\(clientId).json")
        guard let d = try? Data(contentsOf: u) else { return nil }
        return try? JSONDecoder().decode(PlanFile.self, from: d)
    }

    /// Oldest of the cached fire inputs, for "fire data from 3 h ago".
    public var fireDataTimestamp: Date? {
        let ds = [Timestamps.parse(perimeters?.current?.timestamp), Timestamps.parse(wind?.timestamp)].compactMap { $0 }
        return ds.min()
    }
}
