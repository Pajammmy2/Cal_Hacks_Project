import Foundation

/// Loosely typed JSON for fields the navigator passes through (score terms, Claude annotations, tool inputs).
public enum JSONValue: Codable, Equatable, Sendable {
    case null
    case bool(Bool)
    case number(Double)
    case string(String)
    case array([JSONValue])
    case object([String: JSONValue])

    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let n = try? c.decode(Double.self) { self = .number(n) }
        else if let s = try? c.decode(String.self) { self = .string(s) }
        else if let a = try? c.decode([JSONValue].self) { self = .array(a) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .null: try c.encodeNil()
        case .bool(let b): try c.encode(b)
        case .number(let n): try c.encode(n)
        case .string(let s): try c.encode(s)
        case .array(let a): try c.encode(a)
        case .object(let o): try c.encode(o)
        }
    }

    public var string: String? { if case .string(let s) = self { return s }; return nil }
    public var number: Double? { if case .number(let n) = self { return n }; return nil }
    public var bool: Bool? { if case .bool(let b) = self { return b }; return nil }
    public var array: [JSONValue]? { if case .array(let a) = self { return a }; return nil }
    public var object: [String: JSONValue]? { if case .object(let o) = self { return o }; return nil }
    public subscript(key: String) -> JSONValue? { object?[key] }
}

/// Keys of a flat JSON object in file order (JSONDecoder loses order; pronunciation.json depends on it for ties).
enum OrderedJSON {
    static func stringPairs(_ data: Data) throws -> [(String, String)] {
        let chars = Array(data)
        var i = 0
        var out: [(String, String)] = []
        func skipWS() { while i < chars.count, [0x20, 0x09, 0x0A, 0x0D].contains(chars[i]) { i += 1 } }
        func readString() throws -> String {
            guard i < chars.count, chars[i] == 0x22 else { throw CocoaError(.coderReadCorrupt) }
            let start = i
            i += 1
            while i < chars.count, chars[i] != 0x22 {
                if chars[i] == 0x5C { i += 1 }
                i += 1
            }
            guard i < chars.count else { throw CocoaError(.coderReadCorrupt) }
            i += 1
            return try JSONDecoder().decode(String.self, from: Data(chars[start..<i]))
        }
        skipWS()
        guard i < chars.count, chars[i] == 0x7B else { throw CocoaError(.coderReadCorrupt) }
        i += 1
        skipWS()
        if i < chars.count, chars[i] == 0x7D { return out }
        while true {
            skipWS()
            let k = try readString()
            skipWS()
            guard i < chars.count, chars[i] == 0x3A else { throw CocoaError(.coderReadCorrupt) }
            i += 1
            skipWS()
            let v = try readString()
            out.append((k, v))
            skipWS()
            guard i < chars.count else { throw CocoaError(.coderReadCorrupt) }
            if chars[i] == 0x2C { i += 1; continue }
            if chars[i] == 0x7D { break }
            throw CocoaError(.coderReadCorrupt)
        }
        return out
    }
}
