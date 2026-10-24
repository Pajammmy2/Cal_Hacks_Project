import Foundation
import EmberCore

/// Finds the county bundle in the app's Documents (Finder/iTunes file sharing or the Files app) and loads it.
/// Accepted layouts: `<county>.zip` or `bundles/<county>.zip` (unzipped into Application Support), or an
/// already unzipped `<county>/` or `bundles/<county>/` folder containing graph.json.
public struct BundleStore {
    public let documents: URL
    public let support: URL
    let fm = FileManager.default

    public init() {
        documents = fm.urls(for: .documentDirectory, in: .userDomainMask)[0]
        support = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("Ember")
    }

    var extracted: URL { support.appendingPathComponent("bundles") }

    /// shared/*.json shipped in the app (used if a bundle lacks its own shared/ copy).
    public static var appShared: URL? {
        Bundle.main.url(forResource: "profiles", withExtension: "json")?.deletingLastPathComponent()
    }

    func children(_ dir: URL) -> [URL] {
        (try? fm.contentsOfDirectory(at: dir, includingPropertiesForKeys: [.contentModificationDateKey],
                                     options: [.skipsHiddenFiles])) ?? []
    }

    func modified(_ u: URL) -> Date {
        (try? u.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
    }

    /// Bundle folders that contain graph.json, newest first; zips are unzipped first when newer than their copy.
    public func bundleDirs() -> [URL] {
        let roots = [documents, documents.appendingPathComponent("bundles")]
        for root in roots {
            for z in children(root) where z.pathExtension.lowercased() == "zip" {
                let marker = extracted.appendingPathComponent(".\(z.deletingPathExtension().lastPathComponent).unzipped")
                if fm.fileExists(atPath: marker.path), modified(marker) >= modified(z) { continue }
                do {
                    try fm.createDirectory(at: extracted, withIntermediateDirectories: true)
                    try ZipArchive.extract(z, to: extracted)
                    try Data().write(to: marker)
                } catch {
                    NSLog("Ember: could not unzip \(z.lastPathComponent): \(error)")
                }
            }
        }
        var dirs: [URL] = []
        for root in roots + [extracted] {
            for d in children(root) where fm.fileExists(atPath: d.appendingPathComponent("graph.json").path) {
                dirs.append(d)
            }
        }
        return dirs.sorted { modified($0.appendingPathComponent("graph.json")) > modified($1.appendingPathComponent("graph.json")) }
    }

    /// Loads the bundle for `county` if present, else the newest one. Graph is parsed into memory here.
    public func load(county: String?) throws -> EmberBundle {
        let dirs = bundleDirs()
        let pick = dirs.first { county != nil && $0.lastPathComponent == county } ?? dirs.first
        guard let dir = pick else {
            throw EmberError.missing("No map bundle. Copy <county>.zip into the Ember folder in the Files app.")
        }
        return try EmberBundle(dir: dir, sharedFallback: BundleStore.appShared)
    }
}

/// Client profiles entered on this phone (from card QR codes). Stored only on the device.
public struct ProfileStore {
    let url: URL

    public init(support: URL) {
        url = support.appendingPathComponent("profiles.json")
    }

    public func load() -> [ClientProfile] {
        guard let d = try? Data(contentsOf: url) else { return [] }
        return (try? JSONDecoder().decode([ClientProfile].self, from: d)) ?? []
    }

    public func save(_ profiles: [ClientProfile]) {
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        if let d = try? JSONEncoder().encode(profiles) {
            #if os(iOS)
            try? d.write(to: url, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
            #else
            try? d.write(to: url, options: [.atomic])
            #endif
        }
    }
}
