import Foundation
import CoreGraphics

/// Places map overlays (name pills, the Start label, street labels) so that none of them touches the route, another
/// overlay, the user marker or the map edge. The route is drawn first; every pill is drawn above it, and a pill that
/// has no free spot along its anchor is hidden rather than drawn over something. Pure geometry so it can be tested.
public struct OverlayPlacer: Sendable {
    public enum Side: CaseIterable, Sendable { case right, left, below, above }

    public let bounds: CGRect
    /// Half the route's drawn width plus a safety margin: a pill must stay this far from the route centre line.
    public var routeClearance: CGFloat
    /// Gap kept between two overlays.
    public var gap: CGFloat
    public private(set) var placed: [CGRect] = []
    public private(set) var obstacles: [CGRect] = []
    private var routes: [[CGPoint]] = []

    public init(bounds: CGRect, routeClearance: CGFloat = 10, gap: CGFloat = 4) {
        self.bounds = bounds; self.routeClearance = routeClearance; self.gap = gap
    }

    /// A polyline (screen points) that no overlay may cross.
    public mutating func addRoute(_ points: [CGPoint]) { if points.count >= 2 { routes.append(points) } }

    /// Something already drawn that overlays must avoid (user marker, pins, scale bar, compass).
    public mutating func addObstacle(_ rect: CGRect) { obstacles.append(rect) }

    /// True when a rect of this size can sit at `rect` without touching anything.
    public func fits(_ rect: CGRect) -> Bool {
        guard bounds.contains(rect) else { return false }
        let padded = rect.insetBy(dx: -gap, dy: -gap)
        if placed.contains(where: { $0.intersects(padded) }) { return false }
        if obstacles.contains(where: { $0.intersects(padded) }) { return false }
        let buffered = rect.insetBy(dx: -routeClearance, dy: -routeClearance)
        for line in routes where OverlayPlacer.polyline(line, intersects: buffered) { return false }
        return true
    }

    /// Finds a free rect of `size` next to `anchor`, trying each side (in the given order) at increasing distances
    /// and sliding along the map edge when needed. Returns nil when there is no free spot: the caller hides the label.
    public mutating func place(size: CGSize, anchor: CGPoint, offset: CGFloat, sides: [Side] = Side.allCases,
                               maxDistance: CGFloat? = nil) -> CGRect? {
        let limit = maxDistance ?? max(offset * 4, 48)
        var d = offset
        while d <= limit {
            for side in sides {
                var r = OverlayPlacer.rect(size: size, anchor: anchor, side: side, distance: d)
                r = clamp(r)
                if fits(r) { placed.append(r); return r }
            }
            d += max(8, offset)
        }
        return nil
    }

    /// Reserve a rect that was placed by other means (drawn pins, etc.) so later labels avoid it.
    public mutating func reserve(_ rect: CGRect) { placed.append(rect) }

    /// Slide a rect inside the bounds (no clipping at the map edge).
    public func clamp(_ r: CGRect) -> CGRect {
        var r = r
        r.origin.x = min(max(r.origin.x, bounds.minX), max(bounds.minX, bounds.maxX - r.width))
        r.origin.y = min(max(r.origin.y, bounds.minY), max(bounds.minY, bounds.maxY - r.height))
        return r
    }

    public static func rect(size: CGSize, anchor: CGPoint, side: Side, distance: CGFloat) -> CGRect {
        switch side {
        case .right: return CGRect(x: anchor.x + distance, y: anchor.y - size.height / 2, width: size.width, height: size.height)
        case .left:  return CGRect(x: anchor.x - distance - size.width, y: anchor.y - size.height / 2, width: size.width, height: size.height)
        case .below: return CGRect(x: anchor.x - size.width / 2, y: anchor.y + distance, width: size.width, height: size.height)
        case .above: return CGRect(x: anchor.x - size.width / 2, y: anchor.y - distance - size.height, width: size.width, height: size.height)
        }
    }

    /// Preferred sides for a label beside a segment: the side the normal points to first, then the opposite, then
    /// the other axis (so a label never starts out on top of its own line).
    public static func sides(forSegmentFrom a: CGPoint, to b: CGPoint) -> [Side] {
        let dx = b.x - a.x, dy = b.y - a.y
        if abs(dx) >= abs(dy) { return [.below, .above, .right, .left] }   // mostly horizontal line: go above/below
        return [.right, .left, .below, .above]
    }

    // MARK: geometry

    public static func polyline(_ pts: [CGPoint], intersects r: CGRect) -> Bool {
        guard pts.count >= 2 else { return pts.first.map { r.contains($0) } ?? false }
        for i in 1..<pts.count where segment(pts[i - 1], pts[i], intersects: r) { return true }
        return false
    }

    /// Liang–Barsky: does the segment a–b touch the rect?
    public static func segment(_ a: CGPoint, _ b: CGPoint, intersects r: CGRect) -> Bool {
        if r.contains(a) || r.contains(b) { return true }
        var t0: CGFloat = 0, t1: CGFloat = 1
        let dx = b.x - a.x, dy = b.y - a.y
        func clip(_ p: CGFloat, _ q: CGFloat) -> Bool {
            if p == 0 { return q >= 0 }
            let t = q / p
            if p < 0 { if t > t1 { return false }; if t > t0 { t0 = t } }
            else { if t < t0 { return false }; if t < t1 { t1 = t } }
            return true
        }
        guard clip(-dx, a.x - r.minX), clip(dx, r.maxX - a.x), clip(-dy, a.y - r.minY), clip(dy, r.maxY - a.y) else { return false }
        return t0 <= t1
    }
}
