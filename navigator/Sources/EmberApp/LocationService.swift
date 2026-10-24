import Foundation
import CoreLocation

/// GPS fixes for cue progress and arrival. When-in-use only.
@MainActor
public final class LocationService: NSObject, ObservableObject {
    @Published public private(set) var location: CLLocation?
    @Published public private(set) var authorized = false
    private let manager = CLLocationManager()
    var onFix: ((CLLocation) -> Void)?

    public override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyBest
        manager.distanceFilter = 3
        #if os(iOS)
        manager.activityType = .otherNavigation
        manager.pausesLocationUpdatesAutomatically = false
        #endif
    }

    public func start() {
        manager.requestWhenInUseAuthorization()
        manager.startUpdatingLocation()
    }

    public func stop() { manager.stopUpdatingLocation() }
}

extension LocationService: CLLocationManagerDelegate {
    nonisolated public func locationManager(_ m: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let l = locations.last, l.horizontalAccuracy >= 0, l.horizontalAccuracy <= 65 else { return }
        Task { @MainActor in
            self.location = l
            self.onFix?(l)
        }
    }

    nonisolated public func locationManagerDidChangeAuthorization(_ m: CLLocationManager) {
        let s = m.authorizationStatus
        Task { @MainActor in
            #if os(iOS)
            self.authorized = s == .authorizedWhenInUse || s == .authorizedAlways
            #else
            self.authorized = s == .authorizedAlways || s == .authorized
            #endif
            if self.authorized { self.manager.startUpdatingLocation() }
        }
    }

    nonisolated public func locationManager(_ m: CLLocationManager, didFailWithError error: Error) {}
}
