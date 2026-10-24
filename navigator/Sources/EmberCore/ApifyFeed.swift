import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// Apify `county-fire-situation` output: {county, fetched_at, incidents, closures, zones, outages}.
public struct Situation: Sendable, Equatable {
    public struct Closure: Sendable, Equatable { public var lat: Double; public var lon: Double; public var road: String?; public var kind: String? }
    public struct Outage: Sendable, Equatable { public var area: String; public var kind: String?; public var estRestore: String? }

    public var county: String?
    public var fetchedAt: String?
    public var closures: [Closure]
    public var outages: [Outage]

    init(_ v: JSONValue) {
        func num(_ x: JSONValue?) -> Double? {
            if let n = x?.number { return n }
            if let s = x?.string { return Double(s) }
            return nil
        }
        county = v["county"]?.string
        fetchedAt = v["fetched_at"]?.string
        closures = (v["closures"]?.array ?? []).compactMap { c in
            guard let la = num(c["lat"]), let lo = num(c["lon"]) else { return nil }
            return Closure(lat: la, lon: lo, road: c["road"]?.string, kind: c["kind"]?.string)
        }
        outages = (v["outages"]?.array ?? []).compactMap { o in
            guard let a = o["area"]?.string else { return nil }
            return Outage(area: a, kind: o["kind"]?.string, estRestore: o["est_restore"]?.string)
        }
    }
}

/// GET /v2/datasets/<id>/items with a 2 s timeout; the last good result is cached on disk. Nothing waits on it.
public final class ApifyFeed: @unchecked Sendable {
    public static let timeoutS = 2.0
    public static let closureRadiusM = 2000.0
    public static let closureSnapM = 100.0

    public enum Source: Sendable, Equatable { case live, cached, none }

    public struct Result: Sendable {
        public var situation: Situation?
        public var source: Source
        public var fetchedAt: Date?
    }

    let datasetId: String
    let token: String?
    let cacheURL: URL
    let transport: HTTPTransport
    let county: String

    public init(datasetId: String, token: String?, county: String, cacheURL: URL, transport: HTTPTransport = URLSessionTransport()) {
        self.datasetId = datasetId; self.token = token; self.county = county
        self.cacheURL = cacheURL; self.transport = transport
    }

    public var request: URLRequest {
        var c = URLComponents(string: "https://api.apify.com/v2/datasets/\(datasetId)/items")!
        c.queryItems = [URLQueryItem(name: "clean", value: "true"), URLQueryItem(name: "format", value: "json"),
                        URLQueryItem(name: "desc", value: "true"), URLQueryItem(name: "limit", value: "20")]
        var r = URLRequest(url: c.url!, timeoutInterval: ApifyFeed.timeoutS)
        if let token, !token.isEmpty { r.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        return r
    }

    public func fetch(now: Date = Date()) async -> Result {
        let req = request
        let transport = self.transport
        let live: Data? = await withDeadline(ApifyFeed.timeoutS) {
            let (d, resp) = try await transport.send(req)
            guard let h = resp as? HTTPURLResponse, h.statusCode == 200,
                  (try? JSONDecoder().decode([JSONValue].self, from: d)) != nil else { throw EmberError.missing("items") }
            return d
        }
        if let live, let items = try? JSONDecoder().decode([JSONValue].self, from: live) {
            let cache: [String: Any] = ["fetched_ts": now.timeIntervalSince1970,
                                        "items": (try? JSONSerialization.jsonObject(with: live)) ?? []]
            if let d = try? JSONSerialization.data(withJSONObject: cache) {
                try? FileManager.default.createDirectory(at: cacheURL.deletingLastPathComponent(), withIntermediateDirectories: true)
                try? d.write(to: cacheURL, options: .atomic)
            }
            return Result(situation: ApifyFeed.pick(items, county: county), source: .live, fetchedAt: now)
        }
        return cached()
    }

    public func cached() -> Result {
        guard let d = try? Data(contentsOf: cacheURL),
              let o = try? JSONDecoder().decode([String: JSONValue].self, from: d),
              let items = o["items"]?.array else { return Result(situation: nil, source: .none, fetchedAt: nil) }
        let ts = o["fetched_ts"]?.number.map { Date(timeIntervalSince1970: $0) }
        return Result(situation: ApifyFeed.pick(items, county: county), source: .cached, fetchedAt: ts)
    }

    /// Newest item for our county (falls back to any item).
    public static func pick(_ items: [JSONValue], county: String) -> Situation? {
        let c = county.lowercased()
        let all = items.filter { $0.object != nil }
        let mine = all.filter { ($0["county"]?.string ?? "").lowercased().replacingOccurrences(of: " county", with: "") == c }
        let pool = mine.isEmpty ? all : mine
        return pool.max { ($0["fetched_at"]?.string ?? "") < ($1["fetched_at"]?.string ?? "") }.map(Situation.init)
    }

    /// Closures within 2 km of the user, snapped to the nearest graph edge (within 100 m).
    public static func blockedEdges(_ s: Situation?, graph: Graph, lat: Double, lon: Double) -> Set<Int> {
        guard let s else { return [] }
        var out = Set<Int>()
        for c in s.closures where Geo.haversineM(lat, lon, c.lat, c.lon) <= closureRadiusM {
            if let e = graph.nearestEdge(c.lat, c.lon, maxM: closureSnapM) { out.insert(e.edge) }
        }
        return out
    }

    /// Outage whose area mentions the client's ZIP; turns on the device timer.
    public static func outage(_ s: Situation?, zip: String?) -> Situation.Outage? {
        guard let s, let z = zip?.trimmingCharacters(in: .whitespaces).lowercased(), !z.isEmpty else { return nil }
        return s.outages.first { $0.area.lowercased().contains(z) }
    }
}
