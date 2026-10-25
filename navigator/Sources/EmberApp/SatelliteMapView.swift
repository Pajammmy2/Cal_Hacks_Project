#if os(iOS)
import SwiftUI
import MapKit
import EmberCore

/// Non-interactive, north-up satellite MKMapView that keeps a region fitted whatever its size,
/// and reports its visible map rect so the SwiftUI Canvas on top can project lat/lon onto it.
final class FittedMapView: MKMapView {
    var fit: MKCoordinateRegion? { didSet { refit() } }
    /// Navigate follow camera; nil fits `fit` north-up.
    var cameraView: FollowCamera.Viewport? { didSet { refit() } }
    var onVisible: ((MKMapRect) -> Void)?
    private var lastSize = CGSize.zero

    override func layoutSubviews() {
        super.layoutSubviews()
        if bounds.size != lastSize {
            lastSize = bounds.size
            refit()
        }
    }

    func refit() {
        guard bounds.width > 0, bounds.height > 0 else { return }
        if let c = cameraView {
            let aspect = Double(bounds.height / bounds.width)
            let region = MKCoordinateRegion(center: CLLocationCoordinate2D(latitude: c.lat, longitude: c.lon),
                                            latitudinalMeters: c.spanM * aspect, longitudinalMeters: c.spanM)
            setRegion(region, animated: false)
            if abs(camera.heading - c.rotationDeg) > 0.01 {
                let cam = camera
                cam.heading = c.rotationDeg
                setCamera(cam, animated: false)
            }
        } else if let fit {
            if camera.heading != 0 { let cam = camera; cam.heading = 0; setCamera(cam, animated: false) }
            setRegion(regionThatFits(fit), animated: false)
        } else { return }
        let r = visibleMapRect
        DispatchQueue.main.async { [weak self] in self?.onVisible?(r) }
    }
}

struct SatelliteMapView: UIViewRepresentable {
    let fit: MKCoordinateRegion
    var camera: FollowCamera.Viewport? = nil
    let onVisible: (MKMapRect) -> Void
    var onMap: ((MKMapView) -> Void)? = nil

    func makeUIView(context: Context) -> FittedMapView {
        let v = FittedMapView()
        v.mapType = .satellite
        v.pointOfInterestFilter = .excludingAll
        v.showsBuildings = false
        v.showsTraffic = false
        v.showsCompass = false
        v.showsScale = false
        v.showsUserLocation = false
        v.isRotateEnabled = false
        v.isPitchEnabled = false
        v.isScrollEnabled = false
        v.isZoomEnabled = false
        v.isUserInteractionEnabled = false
        v.overrideUserInterfaceStyle = .dark
        v.accessibilityElementsHidden = true
        v.delegate = context.coordinator
        v.onVisible = onVisible
        v.cameraView = camera
        v.fit = fit
        DispatchQueue.main.async { onMap?(v) }
        return v
    }

    func updateUIView(_ v: FittedMapView, context: Context) {
        v.onVisible = onVisible
        if v.cameraView != camera { v.cameraView = camera }
        if let f = v.fit, same(f, fit) { return }
        v.fit = fit
    }

    func makeCoordinator() -> Coordinator { Coordinator(onVisible: onVisible) }

    private func same(_ a: MKCoordinateRegion, _ b: MKCoordinateRegion) -> Bool {
        abs(a.center.latitude - b.center.latitude) < 1e-9 && abs(a.center.longitude - b.center.longitude) < 1e-9 &&
            abs(a.span.latitudeDelta - b.span.latitudeDelta) < 1e-9 && abs(a.span.longitudeDelta - b.span.longitudeDelta) < 1e-9
    }

    final class Coordinator: NSObject, MKMapViewDelegate {
        var onVisible: (MKMapRect) -> Void
        init(onVisible: @escaping (MKMapRect) -> Void) { self.onVisible = onVisible }

        func mapView(_ mapView: MKMapView, regionDidChangeAnimated animated: Bool) {
            let r = mapView.visibleMapRect
            DispatchQueue.main.async { [onVisible] in onVisible(r) }
        }
    }
}
#endif
