import Foundation
import SwiftUI
import ImageIO
#if os(iOS)
import UIKit
import AVFoundation
#endif

/// UIKit-only bits behind one seam so the app type-checks on macOS too.
@MainActor
enum Platform {
    static func haptic() {
        #if os(iOS)
        UINotificationFeedbackGenerator().notificationOccurred(.warning)
        #endif
    }

    static func keepScreenOn(_ on: Bool) {
        #if os(iOS)
        UIApplication.shared.isIdleTimerDisabled = on
        #endif
    }

    /// Spoken audio ducks other apps (spec: AVAudioSession .playback with .duckOthers).
    static func activatePlaybackSession() {
        #if os(iOS)
        let s = AVAudioSession.sharedInstance()
        try? s.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
        try? s.setActive(true)
        #endif
    }

    static func activateRecordSession() {
        #if os(iOS)
        let s = AVAudioSession.sharedInstance()
        try? s.setCategory(.playAndRecord, mode: .measurement, options: [.duckOthers, .defaultToSpeaker])
        try? s.setActive(true)
        #endif
    }

    static func image(at url: URL) -> Image? {
        guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
              let cg = CGImageSourceCreateImageAtIndex(src, 0, nil) else { return nil }
        return Image(decorative: cg, scale: 1)
    }
}
