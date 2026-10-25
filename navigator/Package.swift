// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "EmberNavigator",
    platforms: [.iOS(.v16), .macOS(.v13)],
    products: [
        .library(name: "EmberCore", targets: ["EmberCore"]),
        .library(name: "EmberApp", targets: ["EmberApp"]),
    ],
    targets: [
        .target(name: "EmberCore"),
        .target(name: "EmberApp", dependencies: ["EmberCore"]),
        .testTarget(name: "EmberCoreTests", dependencies: ["EmberCore"]),
        .testTarget(name: "EmberAppTests", dependencies: ["EmberApp"]),
    ]
)
