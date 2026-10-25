import Foundation

public struct ClientDevice: Codable, Sendable, Equatable {
    public var kind: String
    public var hours: Double?
    public var batteryPct: Double?
    enum CodingKeys: String, CodingKey { case kind, hours; case batteryPct = "battery_pct" }
    public init(kind: String, hours: Double? = nil, batteryPct: Double? = nil) {
        self.kind = kind; self.hours = hours; self.batteryPct = batteryPct
    }
}

public struct ClientHome: Codable, Sendable, Equatable {
    public var sleepRoom: String?
    public var pets: String?
    public var chairLocation: String?
    enum CodingKeys: String, CodingKey { case pets; case sleepRoom = "sleep_room"; case chairLocation = "chair_location" }
    public init(sleepRoom: String? = nil, pets: String? = nil, chairLocation: String? = nil) {
        self.sleepRoom = sleepRoom; self.pets = pets; self.chairLocation = chairLocation
    }
}

public struct ClientVoice: Codable, Sendable, Equatable {
    public var kind: String?
    public var voiceId: String?
    enum CodingKeys: String, CodingKey { case kind; case voiceId = "voice_id" }
}

/// A client profile on this phone: the QR payload (CONTRACTS.md) plus the county it came from.
public struct ClientProfile: Codable, Sendable, Equatable, Identifiable {
    public var v: Int?
    public var id: String
    public var name: String
    public var mobility: String
    public var transfer: String?
    public var devices: [ClientDevice]
    public var vision: String?
    public var hearing: String?
    public var cognition: String?
    public var language: String?
    public var home: ClientHome?
    public var lat: Double?
    public var lon: Double?
    public var refugeIds: [String]?
    public var county: String?
    /// Not in the QR payload; used for the Apify outage ZIP match when present.
    public var zip: String?
    public var voice: ClientVoice?

    enum CodingKeys: String, CodingKey {
        case v, id, name, mobility, transfer, devices, vision, hearing, cognition, language, home, lat, lon, county, zip, voice
        case refugeIds = "refuge_ids"
    }

    public init(id: String, name: String, mobility: String, transfer: String? = nil, devices: [ClientDevice] = [],
                home: ClientHome? = nil, lat: Double? = nil, lon: Double? = nil, county: String? = nil, zip: String? = nil) {
        self.id = id; self.name = name; self.mobility = mobility; self.transfer = transfer; self.devices = devices
        self.home = home; self.lat = lat; self.lon = lon; self.county = county; self.zip = zip
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        v = try c.decodeIfPresent(Int.self, forKey: .v)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        mobility = try c.decode(String.self, forKey: .mobility)
        transfer = try c.decodeIfPresent(String.self, forKey: .transfer)
        devices = try c.decodeIfPresent([ClientDevice].self, forKey: .devices) ?? []
        vision = try c.decodeIfPresent(String.self, forKey: .vision)
        hearing = try c.decodeIfPresent(String.self, forKey: .hearing)
        cognition = try c.decodeIfPresent(String.self, forKey: .cognition)
        language = try c.decodeIfPresent(String.self, forKey: .language)
        home = try c.decodeIfPresent(ClientHome.self, forKey: .home)
        lat = try c.decodeIfPresent(Double.self, forKey: .lat)
        lon = try c.decodeIfPresent(Double.self, forKey: .lon)
        refugeIds = try? c.decodeIfPresent([String].self, forKey: .refugeIds)
        county = try c.decodeIfPresent(String.self, forKey: .county)
        zip = try c.decodeIfPresent(String.self, forKey: .zip)
        voice = try? c.decodeIfPresent(ClientVoice.self, forKey: .voice)
    }

    /// shared.profile_key_for; `caregiver` switches a manual-chair client to the pushed variant.
    public func profileKey(caregiver: Bool) throws -> String {
        switch mobility {
        case "manual_chair": return caregiver ? "manual_chair_pushed" : "manual_chair"
        case "power_chair": return "power_chair"
        case "walker", "cane": return "walker"
        case "bedbound": return "bedbound"
        default: throw EmberError.badQR("unknown mobility \(mobility)")
        }
    }

    /// shared.battery_pct_for
    public var batteryPct: Double {
        devices.first { $0.kind == "power_chair" && $0.batteryPct != nil }?.batteryPct ?? 100.0
    }

    public var isBedbound: Bool { mobility == "bedbound" }

    public var mobilityLabel: String {
        switch mobility {
        case "manual_chair": return "Manual chair"
        case "power_chair": return "Power chair"
        case "walker": return "Walker"
        case "cane": return "Cane"
        case "bedbound": return "Bedbound"
        default: return mobility
        }
    }

    /// One SF Symbol per mobility profile (owner pass 3: Lupe uses a cane and showed a wheelchair).
    public var mobilityIcon: String {
        switch mobility {
        case "manual_chair": return "figure.roll"
        case "power_chair": return "figure.roll.runningpace"
        case "walker": return "figure.walk.motion"
        case "cane": return "figure.walk"
        case "bedbound": return "bed.double.fill"
        default: return "person.fill"
        }
    }

    public var transferLabel: String {
        switch transfer {
        case "independent": return "Transfers independently"
        case "slide_board": return "Slide board transfer"
        case "one_person_assist": return "One-person assist"
        case "two_person_lift": return "Two-person lift"
        case "hoyer": return "Hoyer lift"
        case let t?: return t
        case nil: return "Transfer method not set"
        }
    }

    public var equipmentLabel: String {
        let names: [String] = devices.map { d in
            switch d.kind {
            case "oxygen": return d.hours.map { "Oxygen (\(PlanText.fmtHours($0)) h battery)" } ?? "Oxygen"
            case "ventilator": return d.hours.map { "Ventilator (\(PlanText.fmtHours($0)) h battery)" } ?? "Ventilator"
            case "power_chair": return "Power chair (\(Int(d.batteryPct ?? 100))%)"
            case "cpap": return "CPAP"
            default: return d.kind
            }
        }
        return names.isEmpty ? "No equipment" : names.joined(separator: ", ")
    }
}

/// QR payload: `ember://p/<county>/<base64url(json)>`; written with `=` padding, read padded or unpadded.
public enum QRPayload {
    public static func parse(_ text: String) throws -> ClientProfile {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let prefix = "ember://p/"
        guard trimmed.hasPrefix(prefix) else { throw EmberError.badQR("not an Ember card") }
        let rest = trimmed.dropFirst(prefix.count)
        guard let slash = rest.firstIndex(of: "/") else { throw EmberError.badQR("missing county") }
        let county = String(rest[..<slash]).removingPercentEncoding ?? String(rest[..<slash])
        var b64 = String(rest[rest.index(after: slash)...])
            .replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        b64 = b64.trimmingCharacters(in: CharacterSet(charactersIn: "="))
        while b64.count % 4 != 0 { b64 += "=" }
        guard !county.isEmpty, let data = Data(base64Encoded: b64) else { throw EmberError.badQR("bad base64") }
        do {
            var p = try JSONDecoder().decode(ClientProfile.self, from: data)
            p.county = county
            _ = try p.profileKey(caregiver: false)
            return p
        } catch let e as EmberError {
            throw e
        } catch {
            throw EmberError.badQR("bad profile json")
        }
    }

    public static func make(_ p: ClientProfile, county: String) throws -> String {
        var q = p
        q.county = nil
        q.v = 1
        let enc = JSONEncoder()
        enc.outputFormatting = [.sortedKeys]
        let b64 = try enc.encode(q).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
        return "ember://p/\(county)/\(b64)"
    }
}

/// Port of plan.shelter_steps and plan.device_sentences (same strings, so the cached clips match).
public enum PlanText {
    static func pyStrip(_ s: String) -> String {
        let sc = Array(s.unicodeScalars)
        var lo = 0, hi = sc.count
        while lo < hi, Py.isSpace(sc[lo]) { lo += 1 }
        while hi > lo, Py.isSpace(sc[hi - 1]) { hi -= 1 }
        var v = String.UnicodeScalarView()
        v.append(contentsOf: sc[lo..<hi])
        return String(v)
    }

    public static func shelterSteps(_ client: ClientProfile) -> PlanShelter {
        let raw = client.home?.sleepRoom
        let room = pyStrip((raw?.isEmpty == false ? raw! : "bedroom"))
        return PlanShelter(room: room, steps: [
            "Go to the \(room).",
            "Close every window and door. Close the vents.",
            "Put wet towels under the doors.",
            "Fill the tub with water.",
            "Keep your phone on and where you can see it.",
            "Call 911. Say: I am in the \(room).",
        ])
    }

    static func halfHours(_ h: Double) -> Double { ceil(h * 2) / 2.0 }

    public static func fmtHours(_ h: Double) -> String {
        h.rounded(.towardZero) == h && h.isFinite ? String(Int(h)) : String(format: "%.1f", h)
    }

    public static func deviceSentences(_ client: ClientProfile, routeMinutes: Int, fullRangeM: Double) -> [PlanDevice] {
        let need = halfHours(Double(routeMinutes) / 60.0 + 1.0)
        var out: [PlanDevice] = []
        for d in client.devices {
            switch d.kind {
            case "oxygen", "ventilator":
                let h = d.hours ?? 0
                out.append(PlanDevice(kind: d.kind, hours: h, batteryPct: nil, sentence:
                    "Your \(d.kind) battery lasts about \(fmtHours(h)) hours. If the power goes out, leave while it has \(fmtHours(need)) hours left."))
            case "power_chair":
                let pct = d.batteryPct ?? 100
                let km = fullRangeM * pct / 100.0 / 1000.0
                out.append(PlanDevice(kind: d.kind, hours: nil, batteryPct: pct, sentence:
                    "Charge your chair every night. At \(Int(pct)) percent it can go about \(Int(km)) kilometers."))
            case "cpap":
                out.append(PlanDevice(kind: d.kind, hours: nil, batteryPct: nil, sentence:
                    "Your CPAP stops when the power goes out. Take it with you."))
            default:
                break
            }
        }
        return out
    }
}
