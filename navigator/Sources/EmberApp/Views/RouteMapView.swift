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
    var satellites: [SatelliteSnapshot] = []
    var online = false
    var thumbnail = false
    var height: CGFloat? = nil
    /// Navigate: the follow camera (nil = fit the whole route, as on Choose). Heading-up when `rotationDeg` != 0.
    var camera: FollowCamera.Viewport? = nil
    /// Following is paused: the map stays where the hand left it (pinch to zoom, drag to look around).
    var paused = false
    var onUserGesture: (() -> Void)? = nil
    /// Node where the next turn happens: its street label always wins at close zoom.
    var nextTurnNode: Int? = nil

    @State private var manual: FollowCamera.Viewport? = nil
    @State private var gestureBase: FollowCamera.Viewport? = nil
    @State private var liveMap: MKMapView? = nil

    @ScaledMetric(relativeTo: .body) var thumbHeight: CGFloat = 170
    @State private var liveRect: MKMapRect? = nil
    /// Settings → Map: "satellite" (look A: photo under a dark veil) or "drawn" (look C: streets from graph.json).
    @AppStorage(Theme.mapStyleKey) private var mapStyle = "satellite"

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

    /// The camera actually shown: the hand-placed one while paused, else the follow/overview camera.
    var shownCamera: FollowCamera.Viewport? { paused ? (manual ?? camera) : camera }

    /// Ground area a camera view can touch (whatever the rotation), for street culling and snapshot choice.
    func cameraBox(_ c: FollowCamera.Viewport) -> Box {
        let half = c.spanM * 0.75
        let dlat = half / 111_320.0, dlon = half / (111_320.0 * max(cos(Py.radians(c.lat)), 1e-6))
        return Box(s: c.lat - dlat, w: c.lon - dlon, n: c.lat + dlat, e: c.lon + dlon)
    }

    var visibleBox: Box { shownCamera.map(cameraBox) ?? box }

    /// The saved photo for this view: at close zoom the sharpest corridor tile under the camera, else the one
    /// that covers most of the route. nil -> drawn streets (never a blank map).
    var satellite: SatelliteSnapshot? {
        if let c = shownCamera { return SatelliteSnapshot.covering(lat: c.lat, lon: c.lon, spanM: c.spanM, from: satellites) }
        let pts = route.nodes.map { (lat: graph.lat[$0], lon: graph.lon[$0]) }
        return SatelliteSnapshot.best(covering: pts, from: satellites)
    }

    enum Mode { case live, snapshot(SatelliteSnapshot), drawn }

    /// Launch argument `-ember-offline` forces the offline path, so the snapshot fallback can be checked in the Simulator.
    static let forceOffline = ProcessInfo.processInfo.arguments.contains("-ember-offline")

    var mode: Mode {
        if mapStyle == "drawn" { return .drawn }
        #if os(iOS)
        if online && !RouteMapView.forceOffline { return .live }
        #endif
        if let s = satellite { return .snapshot(s) }
        return .drawn
    }

    var isDrawn: Bool { if case .drawn = mode { return true } else { return false } }

    /// lat/lon -> canvas point, plus the ground resolution for the scale bar.
    struct Projection {
        let point: (Double, Double) -> CGPoint
        let metersPerPoint: Double
    }

    /// Camera projection: metres from the centre, rotated so the heading points up. Same maths in every mode
    /// except live, where MapKit's own camera does it and `convert` reads it back.
    func cameraProjection(_ c: FollowCamera.Viewport, _ size: CGSize, rotation: Double) -> (Double, Double) -> CGPoint {
        let mpp = c.spanM / Double(size.width)
        let k = cos(Py.radians(c.lat)) * 111_320.0
        let r = Py.radians(rotation), cr = cos(r), sr = sin(r)
        let cx = Double(size.width) / 2, cy = Double(size.height) / 2
        return { lat, lon in
            let dx = (lon - c.lon) * k, dy = (lat - c.lat) * 111_320.0
            return CGPoint(x: cx + (dx * cr - dy * sr) / mpp, y: cy - (dx * sr + dy * cr) / mpp)
        }
    }

    func projection(_ size: CGSize) -> Projection? {
        guard size.width > 0, size.height > 0 else { return nil }
        let b = box
        var pt: ((Double, Double) -> CGPoint)
        if let c = shownCamera {
            switch mode {
            case .live:
                #if os(iOS)
                guard let map = liveMap, liveRect != nil else { return nil }
                pt = { lat, lon in map.convert(CLLocationCoordinate2D(latitude: lat, longitude: lon), toPointTo: map) }
                #else
                pt = cameraProjection(c, size, rotation: c.rotationDeg)
                #endif
            default:
                pt = cameraProjection(c, size, rotation: c.rotationDeg)
            }
            let p1 = pt(c.lat, c.lon), p2 = pt(c.lat, c.lon + 0.001)
            let d = hypot(p2.x - p1.x, p2.y - p1.y)
            let mpp = d > 0 ? Geo.haversineM(c.lat, c.lon, c.lat, c.lon + 0.001) / Double(d) : c.spanM / Double(size.width)
            return Projection(point: pt, metersPerPoint: mpp)
        }
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

    var rotation: Double { shownCamera?.rotationDeg ?? 0 }

    var body: some View {
        ZStack {
            isDrawn ? Theme.mapLand : Theme.land
            #if os(iOS)
            if case .live = mode {
                SatelliteMapView(fit: box.region, camera: shownCamera, onVisible: { r in liveRect = r }, onMap: { liveMap = $0 })
            }
            #endif
            Canvas(rendersAsynchronously: false) { ctx, size in
                guard let proj = projection(size) else { return }
                if case .snapshot(let s) = mode {
                    if let c = shownCamera {
                        // Photo under a rotating camera: place it with the north-up projection, spin the layer.
                        let flat = cameraProjection(c, size, rotation: 0)
                        let tl = flat(s.n, s.w), br = flat(s.s, s.e)
                        let centre = CGPoint(x: size.width / 2, y: size.height / 2)
                        ctx.drawLayer { l in
                            l.translateBy(x: centre.x, y: centre.y)
                            l.rotate(by: .degrees(-c.rotationDeg))
                            l.draw(Image(decorative: s.image, scale: 1).resizable(),
                                   in: CGRect(x: tl.x - centre.x, y: tl.y - centre.y, width: br.x - tl.x, height: br.y - tl.y))
                        }
                    } else {
                        let b = box
                        ctx.draw(Image(decorative: s.image, scale: 1).resizable(), in: s.fitRect(s: b.s, w: b.w, n: b.n, e: b.e, in: size))
                    }
                }
                if !isDrawn {
                    // The veil: the photo stays readable (roofs, lots, tree lines) but the route, pins and labels win.
                    ctx.fill(Path(CGRect(origin: .zero, size: size)), with: .color(Theme.mapVeil))
                }
                drawOverlays(ctx, size, proj)
            }
            .contentShape(Rectangle())
            .gesture(camera == nil ? nil : mapGesture)
        }
        .onChange(of: paused) { now in if !now { manual = nil; gestureBase = nil } }
        .frame(height: thumbnail ? (height ?? thumbHeight) : nil)
        .clipShape(RoundedRectangle(cornerRadius: Theme.corner, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: Theme.corner, style: .continuous).stroke(Color.white.opacity(0.25), lineWidth: 1))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Map of the route to \(refuge?.name ?? "the refuge"). The green area is the destination, the white dot is where you start.")
    }

    // MARK: gestures (Navigate only): drag to look around, pinch to zoom; either pauses following

    var mapGesture: some Gesture {
        let drag = DragGesture(minimumDistance: 8)
            .onChanged { v in
                guard let base = beginGesture() else { return }
                let mpp = base.spanM / 360.0
                // screen offset -> ground offset, undoing the rotation
                let r = Py.radians(base.rotationDeg), cr = cos(r), sr = sin(r)
                let sx = -Double(v.translation.width) * mpp, sy = Double(v.translation.height) * mpp
                let dx = sx * cr + sy * sr, dy = -sx * sr + sy * cr
                let k = cos(Py.radians(base.lat)) * 111_320.0
                manual = FollowCamera.Viewport(lat: base.lat + dy / 111_320.0, lon: base.lon + dx / max(k, 1e-6),
                                               spanM: base.spanM, rotationDeg: base.rotationDeg)
            }
            .onEnded { _ in gestureBase = nil }
        let pinch = MagnificationGesture()
            .onChanged { scale in
                guard let base = beginGesture(), scale > 0 else { return }
                var c = base
                c.spanM = min(FollowCamera.maxSpanM, max(FollowCamera.minSpanM, base.spanM / Double(scale)))
                manual = c
            }
            .onEnded { _ in gestureBase = nil }
        return drag.simultaneously(with: pinch)
    }

    /// First touch of a gesture: remember where the camera was and tell the model to pause following.
    func beginGesture() -> FollowCamera.Viewport? {
        if gestureBase == nil {
            guard let start = manual ?? camera else { return nil }
            gestureBase = start
            if manual == nil { manual = start }
            if !paused { onUserGesture?() }
        }
        return gestureBase
    }

    // MARK: drawing

    var k: CGFloat { thumbnail ? 0.7 : 1 }

    func onCanvas(_ p: CGPoint, _ size: CGSize, margin: CGFloat = 0) -> Bool {
        p.x >= -margin && p.y >= -margin && p.x <= size.width + margin && p.y <= size.height + margin
    }

    /// Draw order (owner rule): streets, refuge area, the route, then every overlay above the route. Pills are placed by
    /// `OverlayPlacer` so none touches the route, another pill, the user marker, the scale bar, the compass or the map
    /// edge; a pill with no free spot is hidden. Priority: refuge name, Start, then street names.
    func drawOverlays(_ ctx: GraphicsContext, _ size: CGSize, _ proj: Projection) {
        let pt = proj.point
        let routeEdges = Set(route.edges)
        if case .drawn = mode { drawStreets(ctx, size, proj, skipping: routeEdges) }
        drawRefugeArea(ctx, pt)
        drawRoute(ctx, pt)
        var placer = OverlayPlacer(bounds: CGRect(origin: .zero, size: size).insetBy(dx: 5 * k, dy: 5 * k),
                                   routeClearance: 7 * k + 3, gap: 4 * k)
        placer.addRoute(route.nodes.map { pt(graph.lat[$0], graph.lon[$0]) })
        for r in chromeRects(ctx, size, proj.metersPerPoint) { placer.addObstacle(r) }
        let you = youRect(pt)
        if let you { placer.addObstacle(you) }
        let start = drawStartDot(ctx, size, pt)
        if let start { placer.addObstacle(start.rect) }
        let badge = drawRefugeBadge(ctx, size, pt)
        if let badge { placer.addObstacle(badge.rect) }
        if let badge { placeRefugePill(ctx, size, &placer, badge) }
        if let start { placeStartPill(ctx, size, &placer, start) }
        if size.height >= 200 { drawTurnStreetNames(ctx, size, pt, &placer) }
        drawYou(ctx, pt)
        drawCompassAndScale(ctx, size, proj.metersPerPoint)
    }

    func drawStreets(_ ctx: GraphicsContext, _ size: CGSize, _ proj: Projection, skipping: Set<Int>) {
        let b = visibleBox
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
        let casing = Theme.mapLand.opacity(0.9)
        let round = StrokeStyle(lineWidth: 1, lineCap: .round, lineJoin: .round)
        func road(_ path: Path, width: CGFloat, fill: Color) {
            ctx.stroke(path, with: .color(casing), style: StrokeStyle(lineWidth: (width + 2.5) * k, lineCap: round.lineCap, lineJoin: round.lineJoin))
            ctx.stroke(path, with: .color(fill), style: StrokeStyle(lineWidth: width * k, lineCap: round.lineCap, lineJoin: round.lineJoin))
        }
        road(paths, width: 2, fill: Theme.mapRoadMinor.opacity(0.6))
        road(minor, width: 3.5, fill: Theme.mapRoadMinor)
        road(major, width: 6, fill: Theme.mapRoadMajor)
    }

    /// The refuge outline/fill, under the route.
    func drawRefugeArea(_ ctx: GraphicsContext, _ pt: (Double, Double) -> CGPoint) {
        guard let r = refuge else { return }
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
            let c = pt(r.centroidLat, r.centroidLon), rr = 18 * k
            ctx.fill(Path(ellipseIn: CGRect(x: c.x - rr, y: c.y - rr, width: 2 * rr, height: 2 * rr)), with: .color(Theme.safe.opacity(0.35)))
        }
    }

    struct Marker { var anchor: CGPoint; var rect: CGRect; var onScreen: Bool }

    /// The refuge badge (P / building / tree) above the route. Off-screen at close zoom: no badge, the pill alone
    /// sits at the edge nearest the refuge pointing the way.
    func drawRefugeBadge(_ ctx: GraphicsContext, _ size: CGSize, _ pt: (Double, Double) -> CGPoint) -> Marker? {
        guard let r = refuge else { return nil }
        let c = pt(r.centroidLat, r.centroidLon)
        let badge = 17 * k
        guard onCanvas(c, size, margin: 40) || shownCamera == nil else {
            let edge = CGPoint(x: min(max(c.x, 12 * k), size.width - 12 * k), y: min(max(c.y, 44 * k), size.height - 12 * k))
            return Marker(anchor: edge, rect: CGRect(x: edge.x, y: edge.y, width: 0, height: 0), onScreen: false)
        }
        let rect = CGRect(x: c.x - badge, y: c.y - badge, width: 2 * badge, height: 2 * badge)
        ctx.fill(Path(ellipseIn: rect), with: .color(.white))
        ctx.stroke(Path(ellipseIn: rect), with: .color(Theme.safe), lineWidth: 2.5 * k)
        symbol(ctx, RouteMapView.symbolName(for: r.kind), at: c, size: badge * 1.15, color: Color(red: 0.05, green: 0.4, blue: 0.2))
        return Marker(anchor: c, rect: rect, onScreen: true)
    }

    /// Refuge name pill: full name first, the short name when the full one has no free spot, hidden when neither fits.
    func placeRefugePill(_ ctx: GraphicsContext, _ size: CGSize, _ placer: inout OverlayPlacer, _ m: Marker) {
        guard let r = refuge else { return }
        let font = Theme.font(thumbnail ? 15 : 17, .bold)
        let prefix = m.onScreen ? "" : "→ "
        let sides: [OverlayPlacer.Side] = m.onScreen ? [.below, .above, .right, .left] : OverlayPlacer.Side.allCases
        let offset = m.onScreen ? m.rect.width / 2 + 5 * k : 0
        for name in [r.name, r.shortName] {
            let t = Text(prefix + name).font(font).foregroundColor(.white)
            let sz = pillSize(ctx, t, in: size)
            guard sz.width <= size.width - 20 * k else { continue }          // would be clipped: try the short name
            if let rect = placer.place(size: sz, anchor: m.anchor, offset: offset, sides: sides, maxDistance: m.onScreen ? 60 * k : 40 * k) {
                drawPill(ctx, t, in: rect, fill: Color.black.opacity(0.82), stroke: Theme.safe)
                return
            }
        }
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
            walked.move(to: pts[0]); if splitIndex >= 1 { for p in pts[1...splitIndex] { walked.addLine(to: p) } }; walked.addLine(to: split)
        }
        ahead.move(to: split); for p in pts[(splitIndex + 1)...] { ahead.addLine(to: p) }
        let width = 8 * k
        let style = StrokeStyle(lineWidth: width, lineCap: .round, lineJoin: .round)
        ctx.stroke(whole, with: .color(Color.black.opacity(0.9)), style: StrokeStyle(lineWidth: width + 6 * k, lineCap: .round, lineJoin: .round))
        if w > 0 { ctx.stroke(walked, with: .color(Theme.route.opacity(0.45)), style: style) }
        ctx.stroke(ahead, with: .color(Theme.route), style: style)
    }

    /// The street you turn onto, labelled once at each turn (plus the first street), as pills that never overlap
    /// each other, the Start pill or the refuge name. At most `maxTurnLabels`; the rest of the route stays clean.
    static let maxTurnLabels = 4

    func drawTurnStreetNames(_ ctx: GraphicsContext, _ size: CGSize, _ pt: (Double, Double) -> CGPoint, _ placer: inout OverlayPlacer) {
        let edges = route.edges.filter { $0 < graph.edges.count }
        guard edges.count >= 1, route.nodes.count == edges.count + 1 else { return }
        var labels: [(String, Int)] = []   // (street, node index where it begins)
        var lastName: String? = nil
        for (i, ei) in edges.enumerated() {
            let name = graph.edges[ei].name ?? ""
            if !name.isEmpty, name != lastName {
                labels.append((name, i))
            }
            if !name.isEmpty { lastName = name }
        }
        // Keep the first street and the turns onto the longest stretches; drop the rest.
        var lengthByLabel: [Int: Double] = [:]
        for (li, (name, startIdx)) in labels.enumerated() {
            var total = 0.0
            for j in startIdx..<edges.count {
                let e = graph.edges[edges[j]]
                if (e.name ?? "") != name { break }
                total += e.lengthM
            }
            lengthByLabel[li] = total
        }
        // Only labels that land on the canvas count (at close zoom most of the route is off-screen); the street of
        // the upcoming turn is always first.
        func visible(_ li: Int) -> Bool {
            let n0 = route.nodes[labels[li].1]
            return onCanvas(pt(graph.lat[n0], graph.lon[n0]), size, margin: -10)
        }
        let ordered = labels.indices.filter(visible).sorted { a, b in
            let an = route.nodes[labels[a].1] == nextTurnNode, bn = route.nodes[labels[b].1] == nextTurnNode
            if an != bn { return an }
            return (lengthByLabel[a] ?? 0) > (lengthByLabel[b] ?? 0)
        }
        let keep = Set(ordered.prefix(RouteMapView.maxTurnLabels))
        for li in ordered where keep.contains(li) {                 // in priority order: the next turn first
            let (name, startIdx) = labels[li]
            let n0 = route.nodes[startIdx], n1 = route.nodes[min(startIdx + 1, route.nodes.count - 1)]
            let p = pt(graph.lat[n0], graph.lon[n0]), q = pt(graph.lat[n1], graph.lon[n1])
            let mid = CGPoint(x: (p.x + q.x) / 2, y: (p.y + q.y) / 2)
            let t = Text(name).font(Theme.font(thumbnail ? 13 : 15, .bold)).foregroundColor(.white)
            let sz = pillSize(ctx, t, in: size)
            if let rect = placer.place(size: sz, anchor: mid, offset: 10 * k, sides: OverlayPlacer.sides(forSegmentFrom: p, to: q),
                                       maxDistance: 44 * k) {
                drawPill(ctx, t, in: rect, fill: Color.black.opacity(0.78), stroke: Color.white.opacity(0.6))
            }
        }
    }

    /// The Start dot (above the route). Off-screen in the close follow view.
    func drawStartDot(_ ctx: GraphicsContext, _ size: CGSize, _ pt: (Double, Double) -> CGPoint) -> Marker? {
        guard let n = route.nodes.first else { return nil }
        let p = pt(graph.lat[n], graph.lon[n])
        guard onCanvas(p, size, margin: 20) else { return nil }
        let r = 8 * k
        let rect = CGRect(x: p.x - r, y: p.y - r, width: 2 * r, height: 2 * r)
        ctx.fill(Path(ellipseIn: rect), with: .color(.white))
        ctx.stroke(Path(ellipseIn: rect), with: .color(.black), lineWidth: 3 * k)
        return Marker(anchor: p, rect: rect, onScreen: true)
    }

    func placeStartPill(_ ctx: GraphicsContext, _ size: CGSize, _ placer: inout OverlayPlacer, _ m: Marker) {
        let t = Text("Start").font(Theme.font(thumbnail ? 13 : 15, .bold)).foregroundColor(.black)
        let sz = pillSize(ctx, t, in: size)
        if let rect = placer.place(size: sz, anchor: m.anchor, offset: m.rect.width / 2 + 4 * k,
                                   sides: [.right, .left, .below, .above], maxDistance: 48 * k) {
            drawPill(ctx, t, in: rect, fill: .white, stroke: .black)
        }
    }

    /// Where the user marker (halo included) sits; pills keep clear of it.
    func youRect(_ pt: (Double, Double) -> CGPoint) -> CGRect? {
        guard let pos = position else { return nil }
        let p = pt(pos.lat, pos.lon), halo = 20 * k
        return CGRect(x: p.x - halo, y: p.y - halo, width: 2 * halo, height: 2 * halo)
    }

    /// The user marker, drawn last: nothing may cover the person.
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
                l.rotate(by: .degrees(h - rotation))
                l.stroke(arrow, with: .color(.black), style: StrokeStyle(lineWidth: 3 * k, lineJoin: .round))
                l.fill(arrow, with: .color(.white))
            }
        } else {
            let r = 9 * k
            ctx.fill(Path(ellipseIn: CGRect(x: p.x - r, y: p.y - r, width: 2 * r, height: 2 * r)), with: .color(.white))
            ctx.stroke(Path(ellipseIn: CGRect(x: p.x - r, y: p.y - r, width: 2 * r, height: 2 * r)), with: .color(.black), lineWidth: 3 * k)
        }
    }

    // MARK: chrome (scale bar top-left, north arrow top-right)

    struct ScaleGeometry { var box: CGRect; var barWidth: CGFloat; var text: GraphicsContext.ResolvedText }

    func compassRect(_ size: CGSize) -> CGRect {
        let m = 8 * k, r = 15 * k
        return CGRect(x: size.width - m - 2 * r, y: m, width: 2 * r, height: 2 * r)
    }

    func scaleGeometry(_ ctx: GraphicsContext, _ size: CGSize, _ metersPerPoint: Double) -> ScaleGeometry? {
        guard metersPerPoint > 0, metersPerPoint.isFinite else { return nil }
        let m = 8 * k
        let maxPts = Double(size.width) * 0.32
        let candidates: [Double] = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000]
        let metres = candidates.last { $0 / metersPerPoint <= maxPts } ?? 10
        let w = CGFloat(metres / metersPerPoint)
        let label = metres >= 1000 ? "\(Int(metres / 1000)) km" : "\(Int(metres)) m"
        let t = ctx.resolve(Text(label).font(Theme.font(11 * k + 2, .bold)).foregroundColor(.white))
        let tw = t.measure(in: CGSize(width: 200, height: 40))
        let box = CGRect(x: m, y: m, width: max(w, tw.width) + 16 * k, height: tw.height + 10 * k)
        return ScaleGeometry(box: box, barWidth: w, text: t)
    }

    /// Rects of the fixed chrome, reserved before any pill is placed.
    func chromeRects(_ ctx: GraphicsContext, _ size: CGSize, _ metersPerPoint: Double) -> [CGRect] {
        var r = [compassRect(size)]
        if let s = scaleGeometry(ctx, size, metersPerPoint) { r.append(s.box) }
        return r
    }

    func drawCompassAndScale(_ ctx: GraphicsContext, _ size: CGSize, _ metersPerPoint: Double) {
        let cr = compassRect(size), r = cr.width / 2
        let c = CGPoint(x: cr.midX, y: cr.midY)
        ctx.fill(Path(ellipseIn: cr), with: .color(Color.black.opacity(0.7)))
        var tri = Path()
        tri.move(to: CGPoint(x: 0, y: -r * 0.75))
        tri.addLine(to: CGPoint(x: r * 0.32, y: -r * 0.05))
        tri.addLine(to: CGPoint(x: -r * 0.32, y: -r * 0.05))
        tri.closeSubpath()
        ctx.drawLayer { l in           // the arrow turns with the map so it keeps pointing north; the letter stays upright
            l.translateBy(x: c.x, y: c.y)
            l.rotate(by: .degrees(-rotation))
            l.fill(tri, with: .color(.white))
        }
        ctx.draw(Text("N").font(Theme.font(10 * k + 2, .heavy)).foregroundColor(.white), at: CGPoint(x: c.x, y: c.y + r * 0.42), anchor: .center)
        guard let s = scaleGeometry(ctx, size, metersPerPoint) else { return }
        ctx.fill(Path(roundedRect: s.box, cornerRadius: 6 * k), with: .color(Color.black.opacity(0.7)))
        var bar = Path()
        let y = s.box.maxY - 5 * k, x0 = s.box.minX + 8 * k
        bar.move(to: CGPoint(x: x0, y: y - 4 * k)); bar.addLine(to: CGPoint(x: x0, y: y))
        bar.addLine(to: CGPoint(x: x0 + s.barWidth, y: y)); bar.addLine(to: CGPoint(x: x0 + s.barWidth, y: y - 4 * k))
        ctx.stroke(bar, with: .color(.white), lineWidth: 2)
        ctx.draw(s.text, at: CGPoint(x: x0, y: s.box.minY + 3 * k), anchor: .topLeading)
    }

    // MARK: helpers

    func symbol(_ ctx: GraphicsContext, _ name: String, at c: CGPoint, size s: CGFloat, color: Color) {
        var img = ctx.resolve(Image(systemName: name))
        img.shading = .color(color)
        ctx.draw(img, in: CGRect(x: c.x - s / 2, y: c.y - s / 2, width: s, height: s))
    }

    /// Size a pill needs (single line, never wrapped).
    func pillSize(_ ctx: GraphicsContext, _ text: Text, in size: CGSize) -> CGSize {
        let m = ctx.resolve(text).measure(in: CGSize(width: 2000, height: 200))
        return CGSize(width: m.width + 18 * k, height: m.height + 8 * k)
    }

    /// A rounded label in a rect the placer approved.
    func drawPill(_ ctx: GraphicsContext, _ text: Text, in rect: CGRect, fill: Color, stroke: Color) {
        let shape = Path(roundedRect: rect, cornerRadius: rect.height / 2)
        ctx.fill(shape, with: .color(fill))
        ctx.stroke(shape, with: .color(stroke), lineWidth: 1.5 * k)
        ctx.draw(ctx.resolve(text), at: CGPoint(x: rect.midX, y: rect.midY), anchor: .center)
    }
}
