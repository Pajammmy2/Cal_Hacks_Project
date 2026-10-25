import Foundation

/// W1 speech watchdog: a clip that starts but never reports finishing (AVAudioPlayer after an interruption, a
/// truncated file) must not leave the queue waiting forever. The deadline is the clip's own length at its rate
/// plus a small grace.
public enum SpeechWatchdog {
    public static let graceS = 0.8
    public static let minS = 1.0

    public static func timeoutS(clipDuration: Double, rate: Double) -> Double {
        let r = rate > 0 ? rate : 1
        return max(minS, clipDuration / r + graceS)
    }
}
