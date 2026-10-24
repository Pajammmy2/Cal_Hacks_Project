import Foundation

/// shared/*.json, loaded from a bundle's `shared/` copy or the app's resources.
public struct ProfileSpec: Codable, Sendable, Equatable {
    public var label: String
    public var maxGradePct: Double
    public var speedFlatMps: Double
    public var uphillSlowdown: Bool
    public var forbidSteps: String
    public var forbidUnpaved: Bool
    public var penalizeX3: [String]
    public var penalizeX2: [String]?
    public var impassable: [String]?
    public var batteryRange: Bool
    public var fullRangeM: Double?
    public var shelterOnly: Bool

    enum CodingKeys: String, CodingKey {
        case label
        case maxGradePct = "max_grade_pct"
        case speedFlatMps = "speed_flat_mps"
        case uphillSlowdown = "uphill_slowdown"
        case forbidSteps = "forbid_steps"
        case forbidUnpaved = "forbid_unpaved"
        case penalizeX3 = "penalize_x3"
        case penalizeX2 = "penalize_x2"
        case impassable
        case batteryRange = "battery_range"
        case fullRangeM = "full_range_m"
        case shelterOnly = "shelter_only"
    }
}

public struct TurnTemplates: Sendable {
    public var strings: [String: String]
    public var directions: [String]
    public var unnamedPath: String
    public var unnamedStreet: String
    public var pathClasses: [String]

    public subscript(key: String) -> String? { strings[key] }

    static func parse(_ data: Data) throws -> TurnTemplates {
        guard let o = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw EmberError.badBundle("turn_templates.json")
        }
        var strings: [String: String] = [:]
        for (k, v) in o { if let s = v as? String { strings[k] = s } }
        guard let dirs = o["directions"] as? [String], dirs.count == 8,
              let up = o["unnamed_path"] as? String, let us = o["unnamed_street"] as? String,
              let pc = o["path_classes"] as? [String] else { throw EmberError.badBundle("turn_templates.json") }
        return TurnTemplates(strings: strings, directions: dirs, unnamedPath: up, unnamedStreet: us, pathClasses: pc)
    }
}

public struct Phrases: Codable, Sendable {
    public struct Numbers: Codable, Sendable { public var from: Int; public var to: Int }
    public var fixed: [String]
    public var templates: [String: String]
    public var fragments: [String: [String]]
    public var numbers: Numbers
}

public struct IntentsFile: Codable, Sendable {
    public var threshold: Int
    public var intents: [String: [String]]
}

public struct SharedConfig: Sendable {
    public var profiles: [String: ProfileSpec]
    public var templates: TurnTemplates
    public var phrases: Phrases
    /// In file order; Hashing.forCartesia sorts by length with a stable sort, like Python.
    public var pronunciation: [(String, String)]
    public var intents: IntentsFile

    public static func load(from dir: URL) throws -> SharedConfig {
        func data(_ name: String) throws -> Data {
            let u = dir.appendingPathComponent("\(name).json")
            guard let d = try? Data(contentsOf: u) else { throw EmberError.missing("shared/\(name).json") }
            return d
        }
        let dec = JSONDecoder()
        return SharedConfig(
            profiles: try dec.decode([String: ProfileSpec].self, from: data("profiles")),
            templates: try TurnTemplates.parse(data("turn_templates")),
            phrases: try dec.decode(Phrases.self, from: data("phrases")),
            pronunciation: try OrderedJSON.stringPairs(data("pronunciation")),
            intents: try dec.decode(IntentsFile.self, from: data("intents")))
    }

    /// `str.format(**vars)` for the simple `{name}` templates used in shared/.
    public static func format(_ template: String, _ vars: [String: String]) -> String {
        var out = ""
        var i = template.startIndex
        while i < template.endIndex {
            let ch = template[i]
            if ch == "{" {
                let next = template.index(after: i)
                if next < template.endIndex, template[next] == "{" { out.append("{"); i = template.index(after: next); continue }
                if let close = template[next...].firstIndex(of: "}") {
                    let key = String(template[next..<close])
                    out += vars[key] ?? ""
                    i = template.index(after: close)
                    continue
                }
            } else if ch == "}" {
                let next = template.index(after: i)
                if next < template.endIndex, template[next] == "}" { out.append("}"); i = template.index(after: next); continue }
            }
            out.append(ch)
            i = template.index(after: i)
        }
        return out
    }

    public func phrase(_ key: String, _ vars: [String: String] = [:]) -> String {
        SharedConfig.format(phrases.templates[key] ?? key, vars)
    }

    public func template(_ key: String, _ vars: [String: String] = [:]) -> String {
        SharedConfig.format(templates[key] ?? key, vars)
    }
}
