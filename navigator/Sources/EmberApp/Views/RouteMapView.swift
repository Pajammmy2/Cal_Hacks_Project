import SwiftUI
import EmberCore

/// Map thumbnail: nearby streets and the route drawn in a Canvas over an equirectangular projection of the graph.
/// (MBTiles rendering is optional and not done here.)
struct RouteMapView: View {
    let graph: Graph
    let route: Route
    let position: (lat: Double, lon: Double)?
    let refuge: Refuge?
    @ScaledMetric(relativeTo: .body) var height: CGFloat = 200

    struct Box {
        var s: Double, w: Double, n: Double, e: Double
        func pad(_ f: Double) -> Box {
            let dy = max((n - s) * f, 0.0008), dx = max((e - w) * f, 0.0008)
            return Box(s: s - dy, w: w - dx, n: n + dy, e: e + dx)
        }
    }

    var box: Box {
        var b = Box(s: .infinity, w: .infinity, n: -.infinity, e: -.infinity)
        for n in route.nodes {
            b.s = min(b.s, graph.lat[n]); b.n = max(b.n, graph.lat[n])
            b.w = min(b.w, graph.lon[n]); b.e = max(b.e, graph.lon[n])
        }
        return b.pad(0.15)
    }

    var body: some View {
        Canvas { ctx, size in
            let b = box
            let k = cos(Py.radians((b.s + b.n) / 2))
            let sx = size.width / ((b.e - b.w) * k), sy = size.height / (b.n - b.s)
            let scale = min(sx, sy)
            let ox = (size.width - (b.e - b.w) * k * scale) / 2, oy = (size.height - (b.n - b.s) * scale) / 2
            func pt(_ lat: Double, _ lon: Double) -> CGPoint {
                CGPoint(x: ox + (lon - b.w) * k * scale, y: oy + (b.n - lat) * scale)
            }
            var streets = Path()
            var drawn = 0
            for e in graph.edges where drawn < 4000 {
                let (la, lo, lb, lob) = (graph.lat[e.a], graph.lon[e.a], graph.lat[e.b], graph.lon[e.b])
                guard (la >= b.s && la <= b.n && lo >= b.w && lo <= b.e) || (lb >= b.s && lb <= b.n && lob >= b.w && lob <= b.e) else { continue }
                streets.move(to: pt(la, lo)); streets.addLine(to: pt(lb, lob))
                drawn += 1
            }
            ctx.stroke(streets, with: .color(.white.opacity(0.45)), lineWidth: 1.5)
            var line = Path()
            for (i, n) in route.nodes.enumerated() {
                let p = pt(graph.lat[n], graph.lon[n])
                if i == 0 { line.move(to: p) } else { line.addLine(to: p) }
            }
            ctx.stroke(line, with: .color(Theme.accent), style: StrokeStyle(lineWidth: 6, lineCap: .round, lineJoin: .round))
            if let r = refuge, let ep = r.entryPoints.first {
                let p = pt(ep.lat, ep.lon)
                ctx.fill(Path(CGRect(x: p.x - 9, y: p.y - 9, width: 18, height: 18)), with: .color(.white))
            }
            if let pos = position {
                let p = pt(pos.lat, pos.lon)
                ctx.fill(Path(ellipseIn: CGRect(x: p.x - 8, y: p.y - 8, width: 16, height: 16)), with: .color(.white))
                ctx.stroke(Path(ellipseIn: CGRect(x: p.x - 8, y: p.y - 8, width: 16, height: 16)), with: .color(.black), lineWidth: 3)
            }
        }
        .frame(height: height)
        .background(Color.black)
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.white, lineWidth: 1))
        .accessibilityLabel("Map of the route to \(refuge?.name ?? "the refuge"). Square is the destination, circle is you.")
    }
}
