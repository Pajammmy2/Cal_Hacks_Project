import Foundation
import CoreLocation

/// Compass heading for the WhichWay arrow and "Point the phone at the smoke".
@MainActor
public final class CompassService: NSObject, ObservableObject {
    /// Degrees clockwise from true north (magnetic if true north is unavailable); nil without a compass.
    @Published public private(set) var heading: Double?
    private let manager = CLLocationManager()

    public override init() {
        super.init()
        manager.delegate = self
        #if os(iOS)
        manager.headingFilter = 2
        manager.headingOrientation = .portrait
        #endif
    }

    public var available: Bool {
        #if os(iOS)
        return CLLocationManager.headingAvailable()
        #else
        return false
        #endif
    }

    public func start() {
        #if os(iOS)
        if CLLocationManager.headingAvailable() { manager.startUpdatingHeading() }
        #endif
    }

    public func stop() {
        #if os(iOS)
        manager.stopUpdatingHeading()
        #endif
    }
}

extension CompassService: CLLocationManagerDelegate {
    #if os(iOS)
    nonisolated public func locationManager(_ m: CLLocationManager, didUpdateHeading h: CLHeading) {
        guard h.headingAccuracy >= 0 else { return }
        let deg = h.trueHeading >= 0 ? h.trueHeading : h.magneticHeading
        Task { @MainActor in self.heading = deg }
    }

    nonisolated public func locationManagerShouldDisplayHeadingCalibration(_ m: CLLocationManager) -> Bool { true }
    #endif
}
