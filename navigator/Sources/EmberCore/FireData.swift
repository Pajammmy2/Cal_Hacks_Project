import Foundation

/// Which side the fire is on, from the cached perimeter + wind (fresh only if both are under 6 h old).
public struct FireData: Sendable, Equatable {
    public static let freshSeconds: TimeInterval = 6 * 3600
    /// Forward rate of spread as a fraction of wind speed (the "10% rule" of thumb for wind-driven fires).
    public static let spreadFractionOfWind = 0.10

    public var perimeter: Perimeter?
    public var wind: Wind?

    public init(perimeter: Perimeter?, wind: Wind?) { self.perimeter = perimeter; self.wind = wind }

    public var polygon: [[Double]]? {
        guard let p = perimeter?.polygon, p.count >= 3 else { return nil }
        return p
    }

    /// Timestamp of the older of the two inputs (nil if either is missing).
    public var timestamp: Date? {
        guard let p = Timestamps.parse(perimeter?.timestamp), let w = Timestamps.parse(wind?.timestamp) else { return nil }
        return min(p, w)
    }

    public func isFresh(now: Date = Date()) -> Bool {
        guard let t = timestamp else { return false }
        return now.timeIntervalSince(t) < FireData.freshSeconds
    }

    /// Bearing from the client to the fire: nearest perimeter point when a perimeter is known, else upwind.
    public func bearing(lat: Double, lon: Double) -> Double? {
        if let poly = polygon {
            if Geo.pointInPolygon(lat, lon, poly) {
                let c = centroid(poly)
                return Geo.bearingDeg(lat, lon, c.lat, c.lon)
            }
            let p = Geo.nearestPointOnPolygonEdge(lat, lon, poly)
            return Geo.bearingDeg(lat, lon, p.lat, p.lon)
        }
        return wind?.directionFromDeg
    }

    /// Minutes until the fire front could reach the client, or nil when perimeter or wind speed is unknown.
    public func etaMinutes(lat: Double, lon: Double) -> Double? {
        guard let poly = polygon, let ws = wind?.speedMps, ws > 0 else { return nil }
        if Geo.pointInPolygon(lat, lon, poly) { return 0 }
        let d = Geo.distanceToPolygonEdgeM(lat, lon, poly)
        return d / (ws * FireData.spreadFractionOfWind) / 60.0
    }

    func centroid(_ poly: [[Double]]) -> (lat: Double, lon: Double) {
        let pts = poly.count > 1 && poly.first == poly.last ? Array(poly.dropLast()) : poly
        let n = Double(pts.count)
        return (pts.reduce(0) { $0 + $1[1] } / n, pts.reduce(0) { $0 + $1[0] } / n)
    }
}
