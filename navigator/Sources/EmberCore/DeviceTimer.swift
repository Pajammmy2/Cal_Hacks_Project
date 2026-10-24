import Foundation

/// Device-runtime deadline: "Power is out" starts a timer per battery device from the profile;
/// when remaining hours drop below route time + 1 h, the app says "Leave now" on every screen.
public struct DeviceTimer: Sendable, Equatable {
    public struct Remaining: Sendable, Equatable {
        public var kind: String
        /// Spoken label used by the staff pre-generation ("Oxygen", "Ventilator").
        public var label: String
        public var hoursLeft: Double
    }

    public static let marginHours = 1.0
    /// CONTRACTS.md `leave_now_dev` device words (CPAP has no battery deadline).
    public static let labels = ["oxygen": "Oxygen", "ventilator": "Ventilator", "power_chair": "Power chair"]

    public var devices: [ClientDevice]
    public var powerOutSince: Date?

    public init(devices: [ClientDevice], powerOutSince: Date? = nil) {
        self.devices = devices
        self.powerOutSince = powerOutSince
    }

    public var isRunning: Bool { powerOutSince != nil }

    /// Battery devices with a known runtime in hours (oxygen, ventilator; a power chair only if hours were given),
    /// most urgent first.
    public func remaining(now: Date = Date()) -> [Remaining] {
        guard let since = powerOutSince else { return [] }
        let elapsedH = max(0, now.timeIntervalSince(since)) / 3600.0
        return devices.compactMap { d in
            guard let label = DeviceTimer.labels[d.kind], let h = d.hours else { return nil }
            return Remaining(kind: d.kind, label: label, hoursLeft: max(0, h - elapsedH))
        }.sorted { $0.hoursLeft < $1.hoursLeft }
    }

    /// The device that triggers "Leave now", if any.
    public func leaveNow(routeTimeS: Double, now: Date = Date()) -> Remaining? {
        let need = routeTimeS / 3600.0 + DeviceTimer.marginHours
        return remaining(now: now).first { $0.hoursLeft < need }
    }

    /// phrases.json "leave_now_dev": "Leave now. {device} has {n} minutes left." (n matches the staff pre-gen grid).
    public static func leaveNowSentence(_ r: Remaining, config: SharedConfig) -> String {
        let m = Int(floor(r.hoursLeft * 60))
        let n: Int = m <= 120 ? max(1, m) : min(500, m / 10 * 10)
        return config.phrase("leave_now_dev", ["device": r.label, "n": String(n)])
    }
}
