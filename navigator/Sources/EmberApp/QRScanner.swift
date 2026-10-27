import SwiftUI
#if os(iOS)
import AVFoundation
import UIKit

/// Camera QR scanner for the card's `ember://p/...` code.
struct QRScanner: UIViewControllerRepresentable {
    let onCode: (String) -> Void

    func makeUIViewController(context: Context) -> ScannerController {
        let c = ScannerController()
        c.onCode = onCode
        return c
    }

    func updateUIViewController(_ vc: ScannerController, context: Context) {}

    /// Owner must-fix (low-vision / tremor users cannot hold the phone 10 cm from the card): the camera zooms in by
    /// itself while a small QR is in view, the preview pinches, and after 3 s without a decode the phone says how far
    /// to hold the card. Device-verified by the owner (a 1.1 in code from >= 40 cm on iPhone 14 Pro); the Simulator has
    /// no camera.
    final class ScannerController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
        var onCode: ((String) -> Void)?
        private let session = AVCaptureSession()
        private var device: AVCaptureDevice?
        private var delivered = false
        private var pinchStartZoom: CGFloat = 1
        private var hintTimer: Timer?
        static let smallCodeFraction: CGFloat = 0.20      // auto-zoom while the code is narrower than this of the frame
        static let maxAutoZoom: CGFloat = 4
        static let hint = "Hold the card about a foot away."
        static let synth = AVSpeechSynthesizer()

        var maxZoom: CGFloat { min(device?.activeFormat.videoMaxZoomFactor ?? 1, ScannerController.maxAutoZoom) }

        override func viewDidLoad() {
            super.viewDidLoad()
            view.backgroundColor = .black
            guard let device = AVCaptureDevice.default(for: .video),
                  let input = try? AVCaptureDeviceInput(device: device), session.canAddInput(input) else { return }
            self.device = device
            session.addInput(input)
            let out = AVCaptureMetadataOutput()
            guard session.canAddOutput(out) else { return }
            session.addOutput(out)
            out.setMetadataObjectsDelegate(self, queue: .main)
            out.metadataObjectTypes = [.qr]
            let layer = AVCaptureVideoPreviewLayer(session: session)
            layer.videoGravity = .resizeAspectFill
            layer.frame = view.bounds
            view.layer.addSublayer(layer)
            view.addGestureRecognizer(UIPinchGestureRecognizer(target: self, action: #selector(pinch(_:))))
            view.isAccessibilityElement = true
            view.accessibilityLabel = "Camera. Point it at the code on the card. Pinch to zoom."
            DispatchQueue.global(qos: .userInitiated).async { [session] in session.startRunning() }
            hintTimer = Timer.scheduledTimer(withTimeInterval: 3, repeats: false) { [weak self] _ in self?.sayHint() }
        }

        override func viewDidLayoutSubviews() {
            super.viewDidLayoutSubviews()
            view.layer.sublayers?.first?.frame = view.bounds
        }

        override func viewWillDisappear(_ animated: Bool) {
            super.viewWillDisappear(animated)
            hintTimer?.invalidate()
            session.stopRunning()
        }

        func setZoom(_ z: CGFloat, animated: Bool) {
            guard let d = device, (try? d.lockForConfiguration()) != nil else { return }
            let target = max(1, min(z, maxZoom))
            if animated { d.ramp(toVideoZoomFactor: target, withRate: 2) } else { d.videoZoomFactor = target }
            d.unlockForConfiguration()
        }

        @objc func pinch(_ g: UIPinchGestureRecognizer) {
            guard let d = device else { return }
            if g.state == .began { pinchStartZoom = d.videoZoomFactor }
            setZoom(pinchStartZoom * g.scale, animated: false)
        }

        func sayHint() {
            guard !delivered else { return }
            UIAccessibility.post(notification: .announcement, argument: ScannerController.hint)
            let u = AVSpeechUtterance(string: ScannerController.hint)
            u.rate = AVSpeechUtteranceDefaultSpeechRate * 0.9
            ScannerController.synth.speak(u)
        }

        func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput objects: [AVMetadataObject], from connection: AVCaptureConnection) {
            guard !delivered, let code = objects.first as? AVMetadataMachineReadableCodeObject else { return }
            if let s = code.stringValue, s.hasPrefix("ember://") {
                delivered = true
                hintTimer?.invalidate()
                UINotificationFeedbackGenerator().notificationOccurred(.success)
                onCode?(s)
                return
            }
            // Seen but not decoded (too small): zoom in on it. bounds are normalised to the frame (0...1).
            if code.bounds.width < ScannerController.smallCodeFraction, let d = device, d.videoZoomFactor < maxZoom {
                setZoom(d.videoZoomFactor * 1.5, animated: true)
            }
        }
    }
}
#else
/// macOS build stand-in: paste the code text.
struct QRScanner: View {
    let onCode: (String) -> Void
    @State private var text = ""
    var body: some View {
        VStack {
            TextField("ember://p/...", text: $text)
            Button("Add") { onCode(text) }
        }
        .padding()
    }
}
#endif
