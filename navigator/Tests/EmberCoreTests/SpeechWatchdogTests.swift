import Testing
@testable import EmberCore

@Suite struct SpeechWatchdogTests {
    @Test func deadlineIsClipLengthPlusGrace() {
        #expect(abs(SpeechWatchdog.timeoutS(clipDuration: 2.0, rate: 1.0) - 2.8) < 1e-9)
        #expect(abs(SpeechWatchdog.timeoutS(clipDuration: 2.0, rate: 0.85) - (2.0 / 0.85 + 0.8)) < 1e-9)   // "slower" clips get longer
        #expect(SpeechWatchdog.timeoutS(clipDuration: 0, rate: 1.0) == SpeechWatchdog.minS)
        #expect(SpeechWatchdog.timeoutS(clipDuration: 1.0, rate: 0) == 1.8)                               // bad rate treated as 1x
    }
}
