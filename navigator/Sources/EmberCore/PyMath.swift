import Foundation

/// Python float semantics the core relies on, so Swift reproduces the Python engine bit for bit.
public enum Py {
    static let degToRad = Double.pi / 180.0
    static let radToDeg = 180.0 / Double.pi

    public static func radians(_ x: Double) -> Double { x * degToRad }
    public static func degrees(_ x: Double) -> Double { x * radToDeg }

    /// `a % b` for floats (CPython float_rem): result has the sign of the divisor.
    public static func mod(_ a: Double, _ b: Double) -> Double {
        var m = fmod(a, b)
        if m != 0 {
            if (b < 0) != (m < 0) { m += b }
        } else {
            m = copysign(0.0, b)
        }
        return m
    }

    /// `a // b` for floats (CPython float_floor_div).
    public static func floorDiv(_ a: Double, _ b: Double) -> Double {
        var m = fmod(a, b)
        var div = (a - m) / b
        if m != 0 {
            if (b < 0) != (m < 0) {
                m += b
                div -= 1.0
            }
        }
        if div != 0 {
            var fd = floor(div)
            if div - fd > 0.5 { fd += 1.0 }
            return fd
        }
        return copysign(0.0, a / b)
    }

    /// `round(x)` -> int (banker's rounding).
    public static func roundInt(_ x: Double) -> Int { Int(x.rounded(.toNearestOrEven)) }

    /// `round(x, digits)`: correctly rounded decimal, as CPython does via dtoa. Darwin printf is correctly rounded too.
    public static func round(_ x: Double, _ digits: Int) -> Double {
        guard x.isFinite else { return x }
        return Double(String(format: "%.\(digits)f", x)) ?? x
    }

    /// `str.isspace()` / `re` `\s` for str patterns.
    public static func isSpace(_ s: Unicode.Scalar) -> Bool {
        switch s.value {
        case 0x09...0x0D, 0x1C...0x20, 0x85, 0xA0, 0x1680, 0x2000...0x200A, 0x2028, 0x2029, 0x202F, 0x205F, 0x3000:
            return true
        default:
            return false
        }
    }
}
