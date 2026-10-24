import Foundation

/// Port of engine/ember_engine/core/geo.py.
public enum Geo {
    public static let earthR = 6371008.8

    public static func haversineM(_ lat1: Double, _ lon1: Double, _ lat2: Double, _ lon2: Double) -> Double {
        let p1 = Py.radians(lat1), p2 = Py.radians(lat2)
        let dp = p2 - p1
        let dl = Py.radians(lon2 - lon1)
        let a = pow(sin(dp / 2), 2) + cos(p1) * cos(p2) * pow(sin(dl / 2), 2)
        return 2 * earthR * asin(min(1.0, sqrt(a)))
    }

    /// Initial bearing from point 1 to point 2, degrees clockwise from north, 0..360.
    public static func bearingDeg(_ lat1: Double, _ lon1: Double, _ lat2: Double, _ lon2: Double) -> Double {
        let p1 = Py.radians(lat1), p2 = Py.radians(lat2)
        let dl = Py.radians(lon2 - lon1)
        let x = sin(dl) * cos(p2)
        let y = cos(p1) * sin(p2) - sin(p1) * cos(p2) * cos(dl)
        return Py.mod(Py.degrees(atan2(x, y)) + 360.0, 360.0)
    }

    /// Absolute smallest difference between two bearings, 0..180.
    public static func angdiff(_ a: Double, _ b: Double) -> Double {
        let d = abs(Py.mod(a - b, 360.0))
        return d > 180.0 ? 360.0 - d : d
    }

    /// Signed bearing change -180..180, positive = right turn.
    public static func signedTurn(_ bIn: Double, _ bOut: Double) -> Double {
        Py.mod(bOut - bIn + 540.0, 360.0) - 180.0
    }

    public static func directionWord(_ bearing: Double, _ words: [String]) -> String {
        let i = Int(Py.floorDiv(Py.mod(bearing, 360.0) + 22.5, 45.0))
        return words[((i % 8) + 8) % 8]
    }

    static func toXY(_ lat: Double, _ lon: Double, _ lat0: Double) -> (Double, Double) {
        let k = cos(Py.radians(lat0))
        return (Py.radians(lon) * earthR * k, Py.radians(lat) * earthR)
    }

    /// polygon is [[lon, lat], ...].
    public static func pointInPolygon(_ lat: Double, _ lon: Double, _ polygon: [[Double]]) -> Bool {
        var inside = false
        let n = polygon.count
        guard n > 0 else { return false }
        var j = n - 1
        for i in 0..<n {
            let xi = polygon[i][0], yi = polygon[i][1]
            let xj = polygon[j][0], yj = polygon[j][1]
            if (yi > lat) != (yj > lat) {
                let dy = (yj - yi) != 0 ? (yj - yi) : 1e-300
                let xCross = (xj - xi) * (lat - yi) / dy + xi
                if lon < xCross { inside.toggle() }
            }
            j = i
        }
        return inside
    }

    /// Distance from a point to the nearest edge of a polygon ring (local equirectangular projection).
    public static func distanceToPolygonEdgeM(_ lat: Double, _ lon: Double, _ polygon: [[Double]]) -> Double {
        nearestPointOnPolygonEdge(lat, lon, polygon).distance
    }

    /// Nearest point on the ring (lat, lon) and its distance in meters.
    public static func nearestPointOnPolygonEdge(_ lat: Double, _ lon: Double, _ polygon: [[Double]])
        -> (distance: Double, lat: Double, lon: Double) {
        let (px, py) = toXY(lat, lon, lat)
        var best = Double.infinity
        var bx0 = px, by0 = py
        let n = polygon.count
        for i in 0..<n {
            let (ax, ay) = toXY(polygon[i][1], polygon[i][0], lat)
            let (bx, by) = toXY(polygon[(i + 1) % n][1], polygon[(i + 1) % n][0], lat)
            let dx = bx - ax, dy = by - ay
            let l2 = dx * dx + dy * dy
            let t = l2 == 0 ? 0.0 : max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
            let cx = ax + t * dx, cy = ay + t * dy
            let d = hypot(px - cx, py - cy)
            if d < best { best = d; bx0 = cx; by0 = cy }
        }
        let k = cos(Py.radians(lat))
        return (best, Py.degrees(by0 / earthR), Py.degrees(bx0 / (earthR * k)))
    }

    /// Point-to-segment distance in meters (local projection around the point).
    public static func distanceToSegmentM(_ lat: Double, _ lon: Double,
                                          _ alat: Double, _ alon: Double, _ blat: Double, _ blon: Double) -> (d: Double, t: Double) {
        let (px, py) = toXY(lat, lon, lat)
        let (ax, ay) = toXY(alat, alon, lat)
        let (bx, by) = toXY(blat, blon, lat)
        let dx = bx - ax, dy = by - ay
        let l2 = dx * dx + dy * dy
        let t = l2 == 0 ? 0.0 : max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
        return (hypot(px - (ax + t * dx), py - (ay + t * dy)), t)
    }
}
