import SwiftUI
import MapKit
import EmberCore

/// The route map. Three backgrounds, one overlay:
///  - online: live Apple satellite imagery (`SatelliteMapView`, north-up, fitted to the route);
///  - offline with a saved `satellite/<client>_<i>.jpg`: that snapshot, aspect-fitted;
///  - otherwise: streets drawn from graph.json on dark-grey land (equirectangular projection, 4000-edge cap).
/// The Canvas on top draws the same things in every mode: route with casing (walked part dimmer), refuge polygon
/// with icon and name pill, entry pin, Start pin, heading-aware "you" arrow, north arrow and scale bar.
struct RouteMapView: View {
    let graph: Graph
    let route: Route
    let position: (lat: Double, lon: Double)?
    let refuge: Refuge?
    var heading: Double? = nil
    var walkedM: Double? = nil
    var satellite: SatelliteSnapshot? = nil
    var online = false
    var thumbnail = false
    var height: CGFloat? = nil

    @ScaledMetric(relativeTo: .body) var thumbHeight: CGFloat = 170
    @State private var liveRect: MKMapRect? = nil

    struct Box {
        var s: Double, w: Double, n: Double, e: Double
        func pad(_ f: Double) -> Box {
            let dy = max((n - s) * f, 0.0008), dx = max((e - w) * f, 0.0008)
            return Box(s: s - dy, w: w - dx, n: n + dy, e: e + dx)
        }
        var region: MKCoordinateRegion {
            MKCoordinateRegion(center: CLLocationCoordinate2D(latitude: (s + n) / 2, longitude: (w + e) / 2),
                               span: MKCoordinateSpan(latitudeDelta: n - s, longitudeDelta: e - w))
        }
    }

    /// Route, your position and the refuge outline, padded.
    var box: Box {
        var b = Box(s: .infinity, w: .infinity, n: -.infinity, e: -.infinity)
        func add(_ lat: Double, _ lon: Double) {
            b.s = min(b.s, lat); b.n = max(b.n, lat); b.w = min(b.w, lon); b.e = max(b.e, lon)
        }
        for n in route.nodes { add(graph.lat[n], graph.lon[n]) }
        if let p = position { add(p.lat, p.lon) }
        if let r = refuge {
            add(r.centroidLat, r.centroidLon)
            for p in r.polygon ?? [] where p.count >= 2 { add(p[1], p[0]) }
        }
        if !b.s.isFinite { b = Box(s: 0, w: 0, n: 0, e: 0) }
        return b.pad(thumbnail ? 0.12 : 0.18)
    }

    enum Mode { case live, snapshot(SatelliteSnapshot), drawn }

    /// Launch argument `-ember-offline` forces the offline path, so the snapshot fallback can be checked in the Simulator.
    static let forceOffline = ProcessInfo.processInfo.arguments.contains("-ember-offline")

    var mode: Mode {
        #if os(iOS)
        if online && !RouteMapView.forceOffline { return .live }
        #endif
        if let s = satellite { return .snapshot(s) }
        return .drawn
    }

    /// lat/lon -> canvas point, plus the ground resolution for the scale bar.
    struct Projection {
        let point: (Double, Double) -> CGPoint
        let metersPerPoint: Double
    }

    func projection(_ size: CGSize) -> Projection? {
        guard size.width > 0, size.height > 0 else { return nil }
        let b = box
        var pt: ((Double, Double) -> CGPoint)
        switch mode {
        case .live:
            guard let r = liveRect, r.size.width > 0, r.size.height > 0 else { return nil }
            pt = { lat, lon in
                let mp = MKMapPoint(CLLocationCoordinate2D(latitude: lat, longitude: lon))
                return CGPoint(x: (mp.x - r.origin.x) / r.size.width * size.width,
                               y: (mp.y - r.origin.y) / r.size.height * size.height)
            }
        case .snapshot(let s):
            let fit = s.fitRect(s: b.s, w: b.w, n: b.n, e: b.e, in: size)
            pt = { lat, lon in s.point(lat: lat, lon: lon, in: fit) }
        case .drawn:
            let k = cos(Py.radians((b.s + b.n) / 2))
            let scale = min(size.width / ((b.e - b.w) * k), size.height / (b.n - b.s))
            let ox = (size.width - (b.e - b.w) * k * scale) / 2, oy = (size.height - (b.n - b.s) * scale) / 2
            pt = { lat, lon in CGPoint(x: ox + (lon - b.w) * k * scale, y: oy + (b.n - lat) * scale) }
        }
        let midLat = (b.s + b.n) / 2, midLon = (b.w + b.e) / 2
        let p1 = pt(midLat, midLon), p2 = pt(midLat, midLon + 0.001)
        let d = hypot(p2.x - p1.x, p2.y - p1.y)
        let mpp = d > 0 ? Geo.haversineM(midLat, midLon, midLat, midLon + 0.001) / Double(d) : 1
        return Projection(point: pt, metersPerPoint: mpp)
    }

    var body: some View {
        ZStack {
            Theme.land
            #if os(iOS)
            if case .live = mode {
                SatelliteMapView(fit: box.region) { r in liveRect = r }
            }
            #endif
            Canvas(rendersAsynchronously: false) { ctx, size in
                guard let proj = projection(size) else { return }
                if case .snapshot(let s) = mode {
                    let b = box
                    ctx.draw(Image(decorative: s.image, scale: 1).resizable(), in: s.fitRect(s: b.s, w: b.w, n: b.n, e: b.e, in: size))
                }
                drawOverlays(ctx, size, proj)
            }
        }
        .frame(height: thumbnail ? (height ?? thumbHeight) : nil)
        .clipShape(RoundedRectangle(cornerRadius: Theme.corner, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: Theme.corner, style: .continuous).stroke(Color.white.opacity(0.25), lineWidth: 1))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Map of the route to \(refuge?.name ?? "the refuge"). The green area is the destination, the arrow is you.")
    }

    // MARK: drawing

    var k: CGFloat { thumbnail ? 0.7 : 1 }

    func drawOverlays(_ ctx: GraphicsContext, _ size: CGSize, _ proj: Projection) {
        let pt = proj.point
        let routeEdges = Set(route.edges)
        if case .drawn = mode { drawStreets(ctx, size, proj, skipping: routeEdges) }
        drawRefuge(ctx, size, pt)
        drawRoute(ctx, pt)
        if !thumbnail { drawStreetNames(ctx, pt) }
        drawPins(ctx, size, pt)
        drawYou(ctx, pt)
        if !thumbnail { drawCompassAndScale(ctx, size, proj.metersPerPoint) }
    }

    func drawStreets(_ ctx: GraphicsContext, _ size: CGSize, _ proj: Projection, skipping: Set<Int>) {
        let b = box
        var major = Path(), minor = Path(), paths = Path()
        var drawn = 0
        for (i, e) in graph.edges.enumerated() where drawn < 4000 {
            if skipping.contains(i) { continue }
            let (la, lo, lb, lob) = (graph.lat[e.a], graph.lon[e.a], graph.lat[e.b], graph.lon[e.b])
            guard (la >= b.s && la <= b.n && lo >= b.w && lo <= b.e) || (lb >= b.s && lb <= b.n && lob >= b.w && lob <= b.e) else { continue }
            let p = proj.point(la, lo), q = proj.point(lb, lob)
            switch e.roadClass ?? "" {
            case "motorway", "trunk", "primary", "secondary", "tertiary": major.move(to: p); major.addLine(to: q)
            case "footway", "path", "cycleway", "pedestrian", "steps", "service", "track": paths.move(to: p); paths.addLine(to: q)
            default:
                if e.driveway { paths.move(to: p); paths.addLine(to: q) } else { minor.move(to: p); minor.addLine(to: q) }
            }
            drawn += 1
        }
        let casing = Color(white: 0.06)
        let round = StrokeStyle(lineWidth: 1, lineCap: .round, lineJoin: .round)
        func road(_ path: Path, width: CGFloat, fill: Color) {
            ctx.stroke(path, with: .color(casing), style: StrokeStyle(lineWidth: (width + 2.5) * k, lineCap: round.lineCap, lineJoin: round.lineJoin))
            ctx.stroke(path, with: .color(fill), style: StrokeStyle(lineWidth: width * k, lineCap: round.lineCap, lineJoin: round.lineJoin))
        }
        road(paths, width: 2, fill: Color(white: 0.34))
        road(minor, width: 3.5, fill: Color(white: 0.46))
        road(major, width: 5.5, fill: Color(white: 0.58))
    }

    func drawRefuge(_ ctx: GraphicsContext, _ size: CGSize, _ pt: (Double, Double) -> CGPoint) {
        guard let r = refuge else { return }
        let c = pt(r.centroidLat, r.centroidLon)
        if let ring = r.polygon, ring.count >= 3 {
            var p = Path()
            for (i, v) in ring.enumerated() where v.count >= 2 {
                let q = pt(v[1], v[0])
                if i == 0 { p.move(to: q) } else { p.addLine(to: q) }
            }
            p.closeSubpath()
            ctx.fill(p, with: .color(Theme.safe.opacity(0.35)))
            ctx.stroke(p, with: .color(Theme.safe), style: StrokeStyle(lineWidth: 2.5 * k, lineJoin: .round))
        } else {
            let rr = 18 * k
            ctx.fill(Path(ellipseIn: CGRect(x: c.x - rr, y: c.y - rr, width: 2 * rr, height: 2 * rr)), with: .color(Theme.safe.opacity(0.35)))
        }
        let badge = 17 * k
        ctx.fill(Path(ellipseIn: CGRect(x: c.x - badge, y: c.y - badge, width: 2 * badge, height: 2 * badge)), with: .color(.white))
        ctx.stroke(Path(ellipseIn: CGRect(x: c.x - badge, y: c.y - badge, width: 2 * badge, height: 2 * badge)),
                   with: .color(Theme.safe), lineWidth: 2.5 * k)
        symbol(ctx, RouteMapView.symbolName(for: r.kind), at: c, size: badge * 1.15, color: Color(red: 0.05, green: 0.4, blue: 0.2))
        pill(ctx, Text(r.name).font(Theme.font(16, .bold)).foregroundColor(.white),
             at: CGPoint(x: c.x, y: c.y + badge + 5 * k), anchor: .top, in: size, fill: Color.black.opacity(0.78), stroke: Theme.safe)
    }

    static func symbolName(for kind: String?) -> String {
        switch kind ?? "" {
        case "parking", "lot": return "parkingsign"
        case "building", "school", "church", "store", "hospital", "shelter": return "building.2.fill"
        case "park", "field", "open", "grass", "golf", "cemetery": return "tree.fill"
        case "water", "lake", "reservoir", "beach": return "drop.fill"
        default: return "shield.fill"
        }
    }

    func drawRoute(_ ctx: GraphicsContext, _ pt: (Double, Double) -> CGPoint) {
        let pts = route.nodes.map { pt(graph.lat[$0], graph.lon[$0]) }
        guard pts.count >= 2 else { return }
        var cum = [0.0]
        for ei in route.edges where ei < graph.edges.count { cum.append(cum[cum.count - 1] + graph.edges[ei].lengthM) }
        var whole = Path(), walked = Path(), ahead = Path()
        whole.move(to: pts[0]); for p in pts.dropFirst() { whole.addLine(to: p) }
        let w = min(walkedM ?? 0, cum.last ?? 0)
        var split = pts[0]
        var splitIndex = 0
        if w > 0, cum.count == pts.count {
            for i in 1..<pts.count where cum[i - 1] <= w {
                splitIndex = i - 1
                let len = cum[i] - cum[i - 1]
                let t = len > 0 ? min(1, (w - cum[i - 1]) / len) : 1
                split = CGPoint(x: pts[i - 1].x + (pts[i].x - pts[i - 1].x) * t, y: pts[i - 1].y + (pts[i].y - pts[i - 1].y) * t)
            }
            walked.move(to: pts[0]); for p in pts[1...splitIndex] { walked.addLine(to: p) }; walked.addLine(to: split)
        }
        ahead.move(to: split); for p in pts[(splitIndex + 1)...] { ahead.addLine(to: p) }
        let width = 7 * k
        let style = StrokeStyle(lineWidth: width, lineCap: .round, lineJoin: .round)
        ctx.stroke(whole, with: .color(Color.black.opacity(0.85)), style: StrokeStyle(lineWidth: width + 5 * k, lineCap: .round, lineJoin: .round))
        if w > 0 { ctx.stroke(walked, with: .color(Theme.accent.opacity(0.4)), style: style) }
        ctx.stroke(ahead, with: .color(Theme.accent), style: style)
    }

    /// Street names once each along the longest on-screen route edge carrying that name.
    func drawStreetNames(_ ctx: GraphicsContext, _ pt: (Double, Double) -> CGPoint) {
        var best: [String: (CGPoint, CGPoint, CGFloat)] = [:]
        for ei in route.edges where ei < graph.edges.count {
            let e = graph.edges[ei]
            guard let name = e.name, !name.isEmpty else { continue }
            let p = pt(graph.lat[e.a], graph.lon[e.a]), q = pt(graph.lat[e.b], graph.lon[e.b])
            let len = hypot(q.x - p.x, q.y - p.y)
            if len > (best[name]?.2 ?? 0) { best[name] = (p, q, len) }
        }
        for (name, seg) in best {
            let t = ctx.resolve(Text(name).font(Theme.font(13, .semibold)).foregroundColor(.white))
            let w = t.measure(in: CGSize(width: 400, height: 40)).width
            guard seg.2 >= w + 12 else { continue }
            var angle = atan2(seg.1.y - seg.0.y, seg.1.x - seg.0.x)
            if angle > .pi / 2 || angle < -.pi / 2 { angle += .pi }
            let mid = CGPoint(x: (seg.0.x + seg.1.x) / 2, y: (seg.0.y + seg.1.y) / 2)
            ctx.drawLayer { l in
                l.translateBy(x: mid.x, y: mid.y)
                l.rotate(by: .radians(angle))
                l.addFilter(.shadow(color: .black, radius: 2.5))
                l.draw(t, at: CGPoint(x: 0, y: -11), anchor: .center)
            }
        }
    }

    func drawPins(_ ctx: GraphicsContext, _ size: CGSize, _ pt: (Double, Double) -> CGPoint) {
        if let n = route.nodes.first {
            let p = pt(graph.lat[n], graph.lon[n])
            let r = 6 * k
            ctx.fill(Path(ellipseIn: CGRect(x: p.x - r, y: p.y - r, width: 2 * r, height: 2 * r)), with: .color(.white))
            ctx.stroke(Path(ellipseIn: CGRect(x: p.x - r, y: p.y - r, width: 2 * r, height: 2 * r)), with: .color(.black), lineWidth: 2.5 * k)
            pill(ctx, Text("Start").font(Theme.font(thumbnail ? 11 : 13, .bold)).foregroundColor(.black),
                 at: CGPoint(x: p.x + r + 4, y: p.y), anchor: .leading, in: size, fill: .white, stroke: .black)
        }
        if let ep = refuge?.entryPoints.first {
            let p = pt(ep.lat, ep.lon)
            let r = 7 * k, h = 20 * k
            var pin = Path()
            pin.move(to: p)
            pin.addLine(to: CGPoint(x: p.x - r, y: p.y - h + r))
            pin.addArc(center: CGPoint(x: p.x, y: p.y - h + r), radius: r, startAngle: .degrees(180), endAngle: .degrees(0), clockwise: false)
            pin.closeSubpath()
            ctx.stroke(pin, with: .color(.black), style: StrokeStyle(lineWidth: 3 * k, lineJoin: .round))
            ctx.fill(pin, with: .color(.white))
            let dot = 2.5 * k
            ctx.fill(Path(ellipseIn: CGRect(x: p.x - dot, y: p.y - h + r - dot, width: 2 * dot, height: 2 * dot)), with: .color(Theme.safe))
        }
    }

    func drawYou(_ ctx: GraphicsContext, _ pt: (Double, Double) -> CGPoint) {
        guard let pos = position else { return }
        let p = pt(pos.lat, pos.lon)
        let halo = 20 * k
        ctx.fill(Path(ellipseIn: CGRect(x: p.x - halo, y: p.y - halo, width: 2 * halo, height: 2 * halo)), with: .color(Theme.accent.opacity(0.28)))
        if let h = heading {
            let s = 13 * k
            var arrow = Path()
            arrow.move(to: CGPoint(x: 0, y: -s * 1.3))
            arrow.addLine(to: CGPoint(x: s * 0.85, y: s))
            arrow.addLine(to: CGPoint(x: 0, y: s * 0.5))
            arrow.addLine(to: CGPoint(x: -s * 0.85, y: s))
            arrow.closeSubpath()
            ctx.drawLayer { l in
                l.translateBy(x: p.x, y: p.y)
                l.rotate(by: .degrees(h))
                l.stroke(arrow, with: .color(.black), style: StrokeStyle(lineWidth: 3 * k, lineJoin: .round))
                l.fill(arrow, with: .color(.white))
            }
        } else {
            let r = 9 * k
            ctx.fill(Path(ellipseIn: CGRect(x: p.x - r, y: p.y - r, width: 2 * r, height: 2 * r)), with: .color(.white))
            ctx.stroke(Path(ellipseIn: CGRect(x: p.x - r, y: p.y - r, width: 2 * r, height: 2 * r)), with: .color(.black), lineWidth: 3 * k)
        }
    }

    func drawCompassAndScale(_ ctx: GraphicsContext, _ size: CGSize, _ metersPerPoint: Double) {
        let m = 8 * k
        // North arrow, top right.
        let r = 15 * k
        let c = CGPoint(x: size.width - m - r, y: m + r)
        ctx.fill(Path(ellipseIn: CGRect(x: c.x - r, y: c.y - r, width: 2 * r, height: 2 * r)), with: .color(Color.black.opacity(0.7)))
        var tri = Path()
        tri.move(to: CGPoint(x: c.x, y: c.y - r * 0.75))
        tri.addLine(to: CGPoint(x: c.x + r * 0.32, y: c.y - r * 0.05))
        tri.addLine(to: CGPoint(x: c.x - r * 0.32, y: c.y - r * 0.05))
        tri.closeSubpath()
        ctx.fill(tri, with: .color(.white))
        ctx.draw(Text("N").font(Theme.font(10 * k + 2, .heavy)).foregroundColor(.white), at: CGPoint(x: c.x, y: c.y + r * 0.42), anchor: .center)
        // Scale bar, top left (bottom edge is Apple's attribution on the live map).
        guard metersPerPoint > 0, metersPerPoint.isFinite else { return }
        let maxPts = Double(size.width) * 0.32
        let candidates: [Double] = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000]
        let metres = candidates.last { $0 / metersPerPoint <= maxPts } ?? 10
        let w = CGFloat(metres / metersPerPoint)
        let label = metres >= 1000 ? "\(Int(metres / 1000)) km" : "\(Int(metres)) m"
        let t = ctx.resolve(Text(label).font(Theme.font(11 * k + 2, .bold)).foregroundColor(.white))
        let tw = t.measure(in: CGSize(width: 200, height: 40))
        let h = tw.height + 10 * k
        let box = CGRect(x: m, y: m, width: max(w, tw.width) + 16 * k, height: h)
        ctx.fill(Path(roundedRect: box, cornerRadius: 6 * k), with: .color(Color.black.opacity(0.7)))
        var bar = Path()
        let y = box.maxY - 5 * k, x0 = box.minX + 8 * k
        bar.move(to: CGPoint(x: x0, y: y - 4 * k)); bar.addLine(to: CGPoint(x: x0, y: y))
        bar.addLine(to: CGPoint(x: x0 + w, y: y)); bar.addLine(to: CGPoint(x: x0 + w, y: y - 4 * k))
        ctx.stroke(bar, with: .color(.white), lineWidth: 2)
        ctx.draw(t, at: CGPoint(x: x0, y: box.minY + 3 * k), anchor: .topLeading)
    }

    // MARK: helpers

    func symbol(_ ctx: GraphicsContext, _ name: String, at c: CGPoint, size s: CGFloat, color: Color) {
        var img = ctx.resolve(Image(systemName: name))
        img.shading = .color(color)
        ctx.draw(img, in: CGRect(x: c.x - s / 2, y: c.y - s / 2, width: s, height: s))
    }

    /// A rounded label kept inside the canvas (never clipped at an edge).
    func pill(_ ctx: GraphicsContext, _ text: Text, at p: CGPoint, anchor: UnitPoint, in size: CGSize, fill: Color, stroke: Color) {
        let t = ctx.resolve(text)
        let m = t.measure(in: CGSize(width: size.width - 24, height: 200))
        let padX = 9 * k, padY = 4 * k
        var rect = CGRect(x: 0, y: 0, width: m.width + 2 * padX, height: m.height + 2 * padY)
        rect.origin = CGPoint(x: p.x - rect.width * anchor.x, y: p.y - rect.height * anchor.y)
        let edge = 6 * k
        rect.origin.x = min(max(rect.origin.x, edge), max(edge, size.width - edge - rect.width))
        rect.origin.y = min(max(rect.origin.y, edge), max(edge, size.height - edge - rect.height))
        let shape = Path(roundedRect: rect, cornerRadius: rect.height / 2)
        ctx.fill(shape, with: .color(fill))
        ctx.stroke(shape, with: .color(stroke), lineWidth: 1.5 * k)
        ctx.draw(t, at: CGPoint(x: rect.midX, y: rect.midY), anchor: .center)
    }
}
