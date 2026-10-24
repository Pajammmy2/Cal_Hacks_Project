import Foundation
import Security

/// API keys entered at install (Settings). Never hard-coded, never in the repo.
public enum KeychainStore {
    public enum Key: String, CaseIterable {
        case anthropicAPIKey = "anthropic_api_key"
        case cartesiaAPIKey = "cartesia_api_key"
        case cartesiaVoiceId = "cartesia_voice_id"
        case apifyToken = "apify_token"
        case apifyDatasetId = "apify_dataset_id"
    }

    static let service = "org.ember.navigator"

    public static func get(_ key: Key) -> String? {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                kSecAttrAccount as String: key.rawValue, kSecReturnData as String: true,
                                kSecMatchLimit as String: kSecMatchLimitOne]
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let d = out as? Data,
              let s = String(data: d, encoding: .utf8), !s.isEmpty else { return nil }
        return s
    }

    public static func set(_ key: Key, _ value: String?) {
        let base: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                   kSecAttrAccount as String: key.rawValue]
        SecItemDelete(base as CFDictionary)
        guard let v = value?.trimmingCharacters(in: .whitespacesAndNewlines), !v.isEmpty else { return }
        var add = base
        add[kSecValueData as String] = Data(v.utf8)
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(add as CFDictionary, nil)
    }
}
