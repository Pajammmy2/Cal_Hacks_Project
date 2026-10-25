import Foundation
import CoreGraphics
import ImageIO
import MapKit
import EmberCore

/// A pre-rendered satellite image of a route area, stored in the bundle as
/// `satellite/<client_id>_<i>.jpg` + `satellite/<client_id>_<i>.json`
/// (`{"s":lat,"w":lon,"n":lat,"e":lon,"w_px":int,"h_px":int}`), drawn under the route when offline.
/// The image is Web Mercator (what MKMapSnapshotter produces), so latitude is projected through `mercY`.
struct SatelliteSnapshot {
    let image: CGImage
    let s: Double, w: Double, n: Double, e: Double
    let wPx: Int, hPx: Int

    static func mercY(_ lat: Double) -> Double { log(tan(.pi / 4 + Py.radians(lat) / 2)) }
    static func latFromMercY(_ y: Double) -> Double { (2 * atan(exp(y)) - .pi / 2) * 180 / .pi }

    var aspect: CGFloat { CGFloat(wPx) / CGFloat(max(hPx, 1)) }

    /// Ground resolution at the image centre.
    var metersPerPixel: Double { (e - w) * cos(Py.radians((s + n) / 2)) * 111_320.0 / Double(max(wPx, 1)) }

    /// The sharpest saved photo that contains the whole square view (`spanM` across, any rotation) around a point;
    /// failing that, the sharpest one that at least contains the point. nil -> the caller draws streets instead.
    static func covering(lat: Double, lon: Double, spanM: Double, from all: [SatelliteSnapshot]) -> SatelliteSnapshot? {
        let half = spanM * 0.71
        let dlat = half / 111_320.0, dlon = half / (111_320.0 * max(cos(Py.radians(lat)), 1e-6))
        let corners = [(lat + dlat, lon - dlon), (lat + dlat, lon + dlon), (lat - dlat, lon - dlon), (lat - dlat, lon + dlon)]
        let full = all.filter { s in corners.allSatisfy { s.contains(lat: $0.0, lon: $0.1) } }
        if let best = full.min(by: { $0.metersPerPixel < $1.metersPerPixel }) { return best }
        return all.filter { $0.contains(lat: lat, lon: lon) }.min { $0.metersPerPixel < $1.metersPerPixel }
    }

    /// The saved snapshot that covers these points best (whole route or at least most of it).
    static func best(covering pts: [(lat: Double, lon: Double)], from all: [SatelliteSnapshot]) -> SatelliteSnapshot? {
        let ranked = all.map { ($0, $0.coverage(pts)) }.sorted { $0.1 > $1.1 }
        guard let top = ranked.first, top.1 >= 0.6 else { return nil }
        return top.0
    }

    func contains(lat: Double, lon: Double) -> Bool { lat >= s && lat <= n && lon >= w && lon <= e }

    /// Fraction of the given points that fall inside the image.
    func coverage(_ points: [(lat: Double, lon: Double)]) -> Double {
        guard !points.isEmpty else { return 0 }
        return Double(points.filter { contains(lat: $0.lat, lon: $0.lon) }.count) / Double(points.count)
    }

    /// Where the image sits when aspect-fitted into `size`.
    func fitRect(in size: CGSize) -> CGRect {
        let scale = min(size.width / CGFloat(wPx), size.height / CGFloat(hPx))
        let w = CGFloat(wPx) * scale, h = CGFloat(hPx) * scale
        return CGRect(x: (size.width - w) / 2, y: (size.height - h) / 2, width: w, height: h)
    }

    /// Where the image sits so that the lat/lon box `(s, w, n, e)` fills `size` (image cropped at the edges).
    func fitRect(s bs: Double, w bw: Double, n bn: Double, e be: Double, in size: CGSize) -> CGRect {
        let full = CGRect(x: 0, y: 0, width: CGFloat(wPx), height: CGFloat(hPx))
        let tl = point(lat: bn, lon: bw, in: full), br = point(lat: bs, lon: be, in: full)
        let boxW = br.x - tl.x, boxH = br.y - tl.y
        guard boxW > 0, boxH > 0 else { return fitRect(in: size) }
        let scale = min(size.width / boxW, size.height / boxH)
        let cx = (tl.x + br.x) / 2 * scale, cy = (tl.y + br.y) / 2 * scale
        return CGRect(x: size.width / 2 - cx, y: size.height / 2 - cy, width: full.width * scale, height: full.height * scale)
    }

    func point(lat: Double, lon: Double, in rect: CGRect) -> CGPoint {
        let fx = (lon - w) / (e - w)
        let top = SatelliteSnapshot.mercY(n), bottom = SatelliteSnapshot.mercY(s)
        let fy = (top - SatelliteSnapshot.mercY(lat)) / (top - bottom)
        return CGPoint(x: rect.minX + fx * rect.width, y: rect.minY + fy * rect.height)
    }

    // MARK: loading

    static func dir(of bundle: EmberBundle) -> URL { bundle.dir.appendingPathComponent("satellite") }

    @MainActor private static var cache: [URL: SatelliteSnapshot] = [:]

    @MainActor static func load(json url: URL) -> SatelliteSnapshot? {
        if let c = cache[url] { return c }
        guard let d = try? Data(contentsOf: url), let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
              let s = (o["s"] as? NSNumber)?.doubleValue, let w = (o["w"] as? NSNumber)?.doubleValue,
              let n = (o["n"] as? NSNumber)?.doubleValue, let e = (o["e"] as? NSNumber)?.doubleValue, n > s, e > w else { return nil }
        let jpg = url.deletingPathExtension().appendingPathExtension("jpg")
        guard let src = CGImageSourceCreateWithURL(jpg as CFURL, nil), let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else { return nil }
        let snap = SatelliteSnapshot(image: img, s: s, w: w, n: n, e: e,
                                     wPx: (o["w_px"] as? NSNumber)?.intValue ?? img.width, hPx: (o["h_px"] as? NSNumber)?.intValue ?? img.height)
        cache[url] = snap
        return snap
    }

    /// All snapshots saved for a client, in index order.
    @MainActor static func all(bundle: EmberBundle, clientId: String) -> [SatelliteSnapshot] {
        let d = dir(of: bundle)
        guard let names = try? FileManager.default.contentsOfDirectory(atPath: d.path) else { return [] }
        return names.filter { $0.hasPrefix(clientId + "_") && $0.hasSuffix(".json") }.sorted()
            .compactMap { load(json: d.appendingPathComponent($0)) }
    }

    /// The saved snapshot that covers this route best (the whole route, or at least most of it).
    @MainActor static func best(for route: Route, graph: Graph, bundle: EmberBundle?, clientId: String?) -> SatelliteSnapshot? {
        guard let bundle, let clientId else { return nil }
        let pts = route.nodes.map { (lat: graph.lat[$0], lon: graph.lon[$0]) }
        let ranked = all(bundle: bundle, clientId: clientId).map { ($0, $0.coverage(pts)) }.sorted { $0.1 > $1.1 }
        guard let top = ranked.first, top.1 >= 0.6 else { return nil }
        return top.0
    }

    @MainActor static func clearCache() { cache.removeAll() }
}

#if os(iOS)
import UIKit

/// Dev helper: renders and stores satellite snapshots for a client's routes so the offline fallback can be tested.
/// The staff tool will produce the same files server-side; the layout above is the contract.
enum SatelliteCache {
    struct Box { var s: Double, w: Double, n: Double, e: Double }

    static func box(of coords: [(lat: Double, lon: Double)], pad: Double = 0.3) -> Box? {
        guard let f = coords.first else { return nil }
        var b = Box(s: f.lat, w: f.lon, n: f.lat, e: f.lon)
        for c in coords { b.s = min(b.s, c.lat); b.n = max(b.n, c.lat); b.w = min(b.w, c.lon); b.e = max(b.e, c.lon) }
        let dy = max((b.n - b.s) * pad, 0.001), dx = max((b.e - b.w) * pad, 0.001)
        return Box(s: b.s - dy, w: b.w - dx, n: b.n + dy, e: b.e + dx)
    }

    /// Routes to pre-render: the stamped plan's choices when the bundle has one, else a fresh ranking from home.
    static func routes(bundle: EmberBundle, client: ClientProfile) -> [[Int]] {
        if let plan = bundle.plan(clientId: client.id), !plan.choices.isEmpty {
            return plan.choices.map { $0.route.nodes }
        }
        guard let lat = client.lat, let lon = client.lon,
              let key = try? client.profileKey(caregiver: false),
              let profile = try? Profile(key, batteryPct: client.batteryPct, config: bundle.config),
              let origin = bundle.graph.snap(lat, lon, usable: Router.usableOrigin(bundle.graph, profile)).node else { return [] }
        return Router.choose(bundle.graph, refuges: bundle.refuges, profile: profile, origin: origin).map { $0.route.nodes }
    }

    /// Corridor tiles for the follow view: a square this wide every `corridorStepM` along the route, so the
    /// 150 m follow view always has a sharp photo under it offline.
    static let corridorTileM = 420.0, corridorStepM = 180.0

    static func corridorBoxes(_ coords: [(lat: Double, lon: Double)]) -> [Box] {
        var out: [Box] = []
        var sinceLast = Double.infinity
        var prev: (lat: Double, lon: Double)? = nil
        func covered(_ p: (lat: Double, lon: Double)) -> Bool {
            out.contains { b in
                let inner = corridorTileM * 0.25 / 111_320.0
                return p.lat > b.s + inner && p.lat < b.n - inner && p.lon > b.w + inner / cos(Py.radians(p.lat)) && p.lon < b.e - inner / cos(Py.radians(p.lat))
            }
        }
        for c in coords {
            if let p = prev { sinceLast += Geo.haversineM(p.lat, p.lon, c.lat, c.lon) }
            prev = c
            guard sinceLast >= corridorStepM, !covered(c) else { continue }
            sinceLast = 0
            let dlat = corridorTileM / 2 / 111_320.0, dlon = corridorTileM / 2 / (111_320.0 * cos(Py.radians(c.lat)))
            out.append(Box(s: c.lat - dlat, w: c.lon - dlon, n: c.lat + dlat, e: c.lon + dlon))
        }
        return out
    }

    /// Writes `satellite/<client>_<i>.jpg|json` (whole route) and `<client>_<i>_c<j>` corridor tiles for each
    /// route. Returns the number written.
    @MainActor
    static func save(bundle: EmberBundle, client: ClientProfile) async throws -> Int {
        let g = bundle.graph
        let dir = SatelliteSnapshot.dir(of: bundle)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        var written = 0
        for (i, nodes) in routes(bundle: bundle, client: client).enumerated() {
            let coords = nodes.map { (lat: g.lat[$0], lon: g.lon[$0]) }
            guard let b = box(of: coords) else { continue }
            var jobs: [(String, Box, CGFloat)] = [("\(client.id)_\(i)", b, 1000)]
            for (j, cb) in corridorBoxes(coords).enumerated() { jobs.append(("\(client.id)_\(i)_c\(j)", cb, 700)) }
            for (name, b, px) in jobs {
                let k = cos(Py.radians((b.s + b.n) / 2))
                // Keep the picture between square and 16:10 so it still covers the phone's map once the route is fitted.
                let aspect = max(1.0, min(1.6, ((b.e - b.w) * k) / (b.n - b.s)))
                let o = MKMapSnapshotter.Options()
                o.mapType = .satellite
                o.pointOfInterestFilter = .excludingAll
                o.showsBuildings = false
                o.scale = 2
                o.size = CGSize(width: px, height: px / aspect)
                o.region = MKCoordinateRegion(center: CLLocationCoordinate2D(latitude: (b.s + b.n) / 2, longitude: (b.w + b.e) / 2),
                                              span: MKCoordinateSpan(latitudeDelta: b.n - b.s, longitudeDelta: b.e - b.w))
                o.traitCollection = UITraitCollection(userInterfaceStyle: .dark)
                let snap = try await MKMapSnapshotter(options: o).start()
                let img = snap.image
                // The snapshot adjusts the region to its size; recover the exact bounds from two known points.
                let nw = snap.point(for: CLLocationCoordinate2D(latitude: b.n, longitude: b.w))
                let se = snap.point(for: CLLocationCoordinate2D(latitude: b.s, longitude: b.e))
                guard se.x > nw.x, se.y > nw.y else { continue }
                func lon(_ x: CGFloat) -> Double { b.w + Double(x - nw.x) * (b.e - b.w) / Double(se.x - nw.x) }
                let mn = SatelliteSnapshot.mercY(b.n), ms = SatelliteSnapshot.mercY(b.s)
                func lat(_ y: CGFloat) -> Double { SatelliteSnapshot.latFromMercY(mn + Double(y - nw.y) * (ms - mn) / Double(se.y - nw.y)) }
                let meta: [String: Any] = [
                    "s": lat(img.size.height), "w": lon(0), "n": lat(0), "e": lon(img.size.width),
                    "w_px": Int(img.size.width * img.scale), "h_px": Int(img.size.height * img.scale),
                ]
                guard let jpg = img.jpegData(compressionQuality: 0.85) else { continue }
                let base = dir.appendingPathComponent(name)
                try jpg.write(to: base.appendingPathExtension("jpg"), options: .atomic)
                try JSONSerialization.data(withJSONObject: meta).write(to: base.appendingPathExtension("json"), options: .atomic)
                written += 1
            }
        }
        written += try await saveRefugeThumbs(bundle: bundle)
        SatelliteSnapshot.clearCache()
        return written
    }

    /// Writes `thumbs/<refuge id>.jpg` (640x640 satellite, refuge centred) for every refuge, replacing bundle placeholders.
    @MainActor
    static func saveRefugeThumbs(bundle: EmberBundle) async throws -> Int {
        var written = 0
        for r in bundle.refuges {
            guard r.centroid.count >= 2 else { continue }
            let rel = r.thumb ?? "thumbs/\(r.id).jpg"
            let url = bundle.dir.appendingPathComponent(rel)
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            var latSpan = 0.0018, lonSpan = 0.0018 / cos(Py.radians(r.centroid[1]))
            if let poly = r.polygon, let b = box(of: poly.compactMap { $0.count >= 2 ? ($0[1], $0[0]) : nil }, pad: 0.6) {
                latSpan = max(latSpan, b.n - b.s)
                lonSpan = max(lonSpan, b.e - b.w)
            }
            let o = MKMapSnapshotter.Options()
            o.mapType = .satellite
            o.pointOfInterestFilter = .excludingAll
            o.showsBuildings = false
            o.scale = 1
            o.size = CGSize(width: 640, height: 640)
            o.region = MKCoordinateRegion(center: CLLocationCoordinate2D(latitude: r.centroid[1], longitude: r.centroid[0]),
                                          span: MKCoordinateSpan(latitudeDelta: latSpan, longitudeDelta: lonSpan))
            let snap = try await MKMapSnapshotter(options: o).start()
            guard let jpg = snap.image.jpegData(compressionQuality: 0.85) else { continue }
            try jpg.write(to: url, options: .atomic)
            written += 1
        }
        return written
    }
}
#endif
