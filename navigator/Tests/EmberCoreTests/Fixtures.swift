import Foundation
@testable import EmberCore

enum Fixtures {
    static let repo = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    static let fakeDir = repo.appendingPathComponent("bundles/fake")
    static let sharedDir = repo.appendingPathComponent("shared")
    static let parityURL = repo.appendingPathComponent("engine/tests/parity/fake_parity.json")

    static let bundle: EmberBundle = try! EmberBundle(dir: fakeDir, sharedFallback: sharedDir)
    static let config: SharedConfig = try! SharedConfig.load(from: sharedDir)

    static func profile(_ key: String, battery: Double = 100) -> Profile {
        try! Profile(key, batteryPct: battery, config: config)
    }

    static func client(_ mobility: String, devices: [ClientDevice] = [], node: Int = 0) -> ClientProfile {
        let g = bundle.graph
        return ClientProfile(id: "c_test", name: "Test Client", mobility: mobility, transfer: "slide_board", devices: devices,
                             home: ClientHome(sleepRoom: "back bedroom"), lat: g.lat[node], lon: g.lon[node], county: "fake")
    }
}
