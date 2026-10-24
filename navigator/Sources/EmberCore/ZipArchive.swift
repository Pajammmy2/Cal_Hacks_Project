import Foundation
#if canImport(Compression)
import Compression
#endif

/// Minimal ZIP extractor (stored + deflate) so the app opens `bundles/<county>.zip` with no third-party package.
/// Deflate is decoded with Apple's Compression framework (COMPRESSION_ZLIB is raw RFC 1951).
public enum ZipArchive {
    public enum ZipError: Error { case notZip, unsupported(String), corrupt(String), unsafePath(String) }

    struct Entry { let name: String; let method: UInt16; let compSize: Int; let size: Int; let localOffset: Int }

    /// Extracts every file into `dest`, returning the relative paths written. Rejects absolute and `..` paths.
    @discardableResult
    public static func extract(_ zip: URL, to dest: URL) throws -> [String] {
        let data = try Data(contentsOf: zip, options: .mappedIfSafe)
        let bytes = [UInt8](data)
        func u16(_ o: Int) -> Int { Int(bytes[o]) | Int(bytes[o + 1]) << 8 }
        func u32(_ o: Int) -> Int { u16(o) | u16(o + 2) << 16 }
        guard bytes.count >= 22 else { throw ZipError.notZip }
        var eocd = -1
        var i = bytes.count - 22
        while i >= max(0, bytes.count - 22 - 65535) {
            if u32(i) == 0x06054b50 { eocd = i; break }
            i -= 1
        }
        guard eocd >= 0 else { throw ZipError.notZip }
        let count = u16(eocd + 10)
        var p = u32(eocd + 16)
        var entries: [Entry] = []
        for _ in 0..<count {
            guard p + 46 <= bytes.count, u32(p) == 0x02014b50 else { throw ZipError.corrupt("central directory") }
            let method = UInt16(u16(p + 10))
            let comp = u32(p + 20), size = u32(p + 24)
            let nlen = u16(p + 28), xlen = u16(p + 30), clen = u16(p + 32)
            let local = u32(p + 42)
            let name = String(decoding: bytes[(p + 46)..<(p + 46 + nlen)], as: UTF8.self)
            entries.append(Entry(name: name, method: method, compSize: comp, size: size, localOffset: local))
            p += 46 + nlen + xlen + clen
        }
        var written: [String] = []
        let fm = FileManager.default
        for e in entries {
            let parts = e.name.split(separator: "/", omittingEmptySubsequences: true)
            if e.name.hasPrefix("/") || parts.contains("..") { throw ZipError.unsafePath(e.name) }
            if e.name.hasSuffix("/") || parts.first == "__MACOSX" { continue }
            let lo = e.localOffset
            guard lo + 30 <= bytes.count, u32(lo) == 0x04034b50 else { throw ZipError.corrupt(e.name) }
            let start = lo + 30 + u16(lo + 26) + u16(lo + 28)
            guard start + e.compSize <= bytes.count else { throw ZipError.corrupt(e.name) }
            let raw = Data(bytes[start..<(start + e.compSize)])
            let out: Data
            switch e.method {
            case 0: out = raw
            case 8: out = try inflate(raw, size: e.size)
            default: throw ZipError.unsupported("method \(e.method) for \(e.name)")
            }
            let url = dest.appendingPathComponent(e.name)
            try fm.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try out.write(to: url, options: .atomic)
            written.append(e.name)
        }
        return written
    }

    static func inflate(_ data: Data, size: Int) throws -> Data {
        if size == 0 { return Data() }
        guard !data.isEmpty else { throw ZipError.corrupt("empty deflate stream") }
        #if canImport(Compression)
        var out = Data(count: size)
        let n = out.withUnsafeMutableBytes { (dst: UnsafeMutableRawBufferPointer) -> Int in
            data.withUnsafeBytes { (src: UnsafeRawBufferPointer) -> Int in
                compression_decode_buffer(dst.bindMemory(to: UInt8.self).baseAddress!, size,
                                          src.bindMemory(to: UInt8.self).baseAddress!, data.count, nil, COMPRESSION_ZLIB)
            }
        }
        guard n == size else { throw ZipError.corrupt("inflate \(n) != \(size)") }
        return out
        #else
        throw ZipError.unsupported("deflate")
        #endif
    }
}
