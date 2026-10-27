import Foundation
import AVFoundation
import Network
import Speech

/// Voice in. The mic opens only on the button; recognition is on-device (works in airplane mode).
/// `online` comes from NWPathMonitor: with signal the transcript goes to Claude (VoiceAgent), otherwise straight to
/// the intent matcher.
@MainActor
public final class VoiceController: ObservableObject {
    public static let silenceS = 1.5
    public static let maxListenS = 8.0

    @Published public private(set) var listening = false
    @Published public private(set) var online = false
    @Published public private(set) var partial = ""

    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private let engine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var silenceTimer: Timer?
    private var maxTimer: Timer?
    private var onFinal: ((String) -> Void)?
    private let monitor = NWPathMonitor()
    var onlineChanged: ((Bool) -> Void)?

    public init() {
        monitor.pathUpdateHandler = { [weak self] path in
            let up = path.status == .satisfied
            Task { @MainActor in
                guard let self, self.online != up else { return }
                self.online = up
                self.onlineChanged?(up)
            }
        }
        monitor.start(queue: DispatchQueue(label: "ember.path"))
    }

    public func requestAuthorization() {
        SFSpeechRecognizer.requestAuthorization { _ in }
        #if os(iOS)
        AVAudioSession.sharedInstance().requestRecordPermission { _ in }
        #endif
    }

    /// Mic button: start listening, or stop and deliver what was heard.
    public func toggle(onFinal: @escaping (String) -> Void) {
        if listening { finish() } else { start(onFinal: onFinal) }
    }

    /// installTap raises an uncatchable NSException on a 0 Hz / 0-channel input format (no microphone route:
    /// Simulator on a headless Mac, a Bluetooth route mid-switch, mic denied on some devices). Treat it as
    /// "heard nothing" instead of crashing the app.
    nonisolated static func micFormatIsUsable(sampleRate: Double, channels: UInt32) -> Bool {
        sampleRate > 0 && channels > 0
    }

    func start(onFinal: @escaping (String) -> Void) {
        guard let recognizer, recognizer.isAvailable else {
            onFinal("")
            return
        }
        self.onFinal = onFinal
        partial = ""
        Platform.activateRecordSession()
        let req = SFSpeechAudioBufferRecognitionRequest()
        req.requiresOnDeviceRecognition = true
        req.shouldReportPartialResults = true
        request = req
        let input = engine.inputNode
        let fmt = input.outputFormat(forBus: 0)
        guard VoiceController.micFormatIsUsable(sampleRate: fmt.sampleRate, channels: fmt.channelCount) else {
            cleanup()
            onFinal("")
            return
        }
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: fmt) { buf, _ in req.append(buf) }
        engine.prepare()
        do { try engine.start() } catch {
            cleanup()
            onFinal("")
            return
        }
        listening = true
        task = recognizer.recognitionTask(with: req) { [weak self] result, error in
            let text = result?.bestTranscription.formattedString
            let isFinal = result?.isFinal ?? false
            Task { @MainActor in
                guard let self, self.listening else { return }
                if let text { self.partial = text; self.armSilenceTimer() }
                if isFinal || error != nil { self.finish() }
            }
        }
        maxTimer = Timer.scheduledTimer(withTimeInterval: VoiceController.maxListenS, repeats: false) { [weak self] _ in
            Task { @MainActor in self?.finish() }
        }
    }

    private func armSilenceTimer() {
        silenceTimer?.invalidate()
        silenceTimer = Timer.scheduledTimer(withTimeInterval: VoiceController.silenceS, repeats: false) { [weak self] _ in
            Task { @MainActor in self?.finish() }
        }
    }

    func finish() {
        guard listening else { return }
        let text = partial
        cleanup()
        let cb = onFinal
        onFinal = nil
        cb?(text)
    }

    private func cleanup() {
        listening = false
        silenceTimer?.invalidate(); silenceTimer = nil
        maxTimer?.invalidate(); maxTimer = nil
        engine.stop()
        engine.inputNode.removeTap(onBus: 0)
        request?.endAudio()
        task?.cancel()
        request = nil
        task = nil
        Platform.activatePlaybackSession()
    }
}
