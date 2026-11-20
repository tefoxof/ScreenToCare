const DATABASE_NAME = 'carebridge-secure-offline';
const DATABASE_VERSION = 1;
const QUEUE_STORE = 'encrypted-queue';
const KEY_STORE = 'device-keys';
const DEVICE_KEY_ID = 'offline-aes-gcm-v1';
const LEGACY_QUEUE_KEY = 'cb_offline_queue';

function requestResult(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error('IndexedDB request failed.'));
  });
}

function transactionResult(transaction) {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error || new Error('IndexedDB transaction failed.'));
    transaction.onabort = () => reject(transaction.error || new Error('IndexedDB transaction was aborted.'));
  });
}

function bytesToBase64(bytes) {
  let binary = '';
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

function base64ToBytes(value) {
  const binary = atob(value);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

class OfflineSyncManager {
  constructor(syncEndpoint) {
    this.syncEndpoint = syncEndpoint;
    this.deviceId = `device_${crypto.randomUUID()}`;
    this.isFlushing = false;
    this.isEnabled = false;
    this.databasePromise = null;
    this.initNetworkListeners();
  }

  initNetworkListeners() {
    window.addEventListener('online', () => {
      if (!this.isEnabled) return;
      this.flushQueue().catch((error) => {
        console.error('Automatic offline sync failed.', error);
      });
    });
    window.addEventListener('offline', () => {
      console.info('Network offline. Switching to queue-and-forward mode.');
    });
  }

  setEnabled(isEnabled) {
    this.isEnabled = isEnabled;
    if (isEnabled && navigator.onLine) {
      this.flushQueue().catch((error) => {
        console.error('Automatic offline sync failed.', error);
      });
    }
  }

  async openDatabase() {
    if (!window.isSecureContext || !crypto.subtle) {
      throw new Error('Encrypted offline storage requires HTTPS or localhost with Web Crypto support.');
    }
    if (!window.indexedDB) {
      throw new Error('Encrypted offline storage is unavailable because IndexedDB is not supported.');
    }
    if (!this.databasePromise) {
      this.databasePromise = new Promise((resolve, reject) => {
        const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
        request.onupgradeneeded = () => {
          const database = request.result;
          if (!database.objectStoreNames.contains(QUEUE_STORE)) {
            database.createObjectStore(QUEUE_STORE, { keyPath: 'queue_id' });
          }
          if (!database.objectStoreNames.contains(KEY_STORE)) {
            database.createObjectStore(KEY_STORE, { keyPath: 'id' });
          }
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error || new Error('Could not open encrypted offline storage.'));
        request.onblocked = () => reject(new Error('Encrypted offline storage upgrade is blocked by another tab.'));
      }).catch((error) => {
        this.databasePromise = null;
        throw error;
      });
    }
    const database = await this.databasePromise;
    await this.getDeviceKey(database);
    await this.migrateLegacyQueue(database);
    return database;
  }

  async getDeviceKey(database) {
    const readTransaction = database.transaction(KEY_STORE, 'readonly');
    const existing = await requestResult(readTransaction.objectStore(KEY_STORE).get(DEVICE_KEY_ID));
    await transactionResult(readTransaction);
    if (existing?.key) return existing.key;

    const queueTransaction = database.transaction(QUEUE_STORE, 'readonly');
    const queuedRecords = await requestResult(queueTransaction.objectStore(QUEUE_STORE).count());
    await transactionResult(queueTransaction);
    if (queuedRecords > 0) {
      throw new Error('The offline encryption key is missing; queued records were preserved but cannot be decrypted.');
    }

    const generatedKey = await crypto.subtle.generateKey(
      { name: 'AES-GCM', length: 256 },
      false,
      ['encrypt', 'decrypt']
    );
    const writeTransaction = database.transaction(KEY_STORE, 'readwrite');
    const writeRequest = writeTransaction.objectStore(KEY_STORE).add({
      id: DEVICE_KEY_ID,
      key: generatedKey
    });
    try {
      await requestResult(writeRequest);
      await transactionResult(writeTransaction);
      return generatedKey;
    } catch (error) {
      if (error?.name !== 'ConstraintError') throw error;
      const retryTransaction = database.transaction(KEY_STORE, 'readonly');
      const winner = await requestResult(retryTransaction.objectStore(KEY_STORE).get(DEVICE_KEY_ID));
      await transactionResult(retryTransaction);
      if (!winner?.key) {
        throw new Error('Could not initialize the device encryption key.', { cause: error });
      }
      return winner.key;
    }
  }

  async encryptRecord(database, record) {
    const key = await this.getDeviceKey(database);
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const plaintext = new TextEncoder().encode(JSON.stringify(record));
    const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, plaintext);
    return {
      queue_id: record.queue_id,
      queued_at: record.local_queued_at,
      version: 1,
      iv: bytesToBase64(iv),
      ciphertext: bytesToBase64(new Uint8Array(ciphertext))
    };
  }

  async decryptRecord(database, encryptedRecord) {
    try {
      const key = await this.getDeviceKey(database);
      const plaintext = await crypto.subtle.decrypt(
        { name: 'AES-GCM', iv: base64ToBytes(encryptedRecord.iv) },
        key,
        base64ToBytes(encryptedRecord.ciphertext)
      );
      return JSON.parse(new TextDecoder().decode(plaintext));
    } catch (error) {
      throw new Error(
        `Could not decrypt offline record ${encryptedRecord.queue_id}: ${error.message}`,
        { cause: error }
      );
    }
  }

  async migrateLegacyQueue(database) {
    const legacyValue = localStorage.getItem(LEGACY_QUEUE_KEY);
    if (legacyValue === null) return;
    let legacyQueue;
    try {
      legacyQueue = JSON.parse(legacyValue);
    } catch {
      throw new Error('The previous offline queue is malformed; it has not been removed.');
    }
    if (!Array.isArray(legacyQueue)) {
      throw new Error('The previous offline queue is invalid; it has not been removed.');
    }
    for (const legacyRecord of legacyQueue) {
      const record = {
        ...legacyRecord,
        queue_id: legacyRecord.queue_id || crypto.randomUUID(),
        local_queued_at: legacyRecord.local_queued_at || new Date().toISOString()
      };
      await this.storeEncryptedRecord(database, await this.encryptRecord(database, record));
    }
    localStorage.removeItem(LEGACY_QUEUE_KEY);
    this.notifyQueueChange(await this.getEncryptedQueueCount(database));
  }

  async storeEncryptedRecord(database, encryptedRecord) {
    const transaction = database.transaction(QUEUE_STORE, 'readwrite');
    const request = transaction.objectStore(QUEUE_STORE).put(encryptedRecord);
    await requestResult(request);
    await transactionResult(transaction);
  }

  async getEncryptedQueue(database) {
    const transaction = database.transaction(QUEUE_STORE, 'readonly');
    const records = await requestResult(transaction.objectStore(QUEUE_STORE).getAll());
    await transactionResult(transaction);
    return records.sort((left, right) => left.queued_at.localeCompare(right.queued_at));
  }

  async getEncryptedQueueCount(database) {
    const transaction = database.transaction(QUEUE_STORE, 'readonly');
    const count = await requestResult(transaction.objectStore(QUEUE_STORE).count());
    await transactionResult(transaction);
    return count;
  }

  async getQueue() {
    const database = await this.openDatabase();
    const encryptedQueue = await this.getEncryptedQueue(database);
    return Promise.all(encryptedQueue.map((record) => this.decryptRecord(database, record)));
  }

  async getQueueCount() {
    const database = await this.openDatabase();
    return this.getEncryptedQueueCount(database);
  }

  notifyQueueChange(count) {
    window.dispatchEvent(new CustomEvent('cb_queue_updated', { detail: { count } }));
  }

  async saveToLocalQueue(screeningPayload) {
    if (screeningPayload.consent_signed !== true) {
      throw new Error('Signed POPIA / Data Protection Act consent is required before offline storage.');
    }
    const database = await this.openDatabase();
    const record = {
      ...screeningPayload,
      queue_id: screeningPayload.queue_id || crypto.randomUUID(),
      local_queued_at: new Date().toISOString()
    };
    await this.storeEncryptedRecord(database, await this.encryptRecord(database, record));
    this.notifyQueueChange(await this.getEncryptedQueueCount(database));
    return record;
  }

  async flushQueue() {
    if (this.isFlushing) return null;
    if (!this.isEnabled) {
      return { records_processed: 0, failed_count: 0, failures: [] };
    }
    if (!navigator.onLine) {
      return { records_processed: 0, failed_count: 0, failures: [] };
    }

    this.isFlushing = true;
    try {
      const database = await this.openDatabase();
      const encryptedQueue = await this.getEncryptedQueue(database);
      if (encryptedQueue.length === 0) {
        this.notifyQueueChange(0);
        return { records_processed: 0, failed_count: 0, failures: [] };
      }

      const queue = await Promise.all(
        encryptedQueue.map((record) => this.decryptRecord(database, record))
      );
      const response = await fetch(this.syncEndpoint, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ device_id: this.deviceId, synced_records: queue })
      });
      if (!response.ok) {
        throw new Error(`Offline sync failed with HTTP ${response.status}.`);
      }

      const result = await response.json();
      const failures = result.failures || [];
      const processedQueueIds = new Set(result.processed_queue_ids || []);
      const failedQueueIds = new Set(failures.map((failure) => failure.queue_id).filter(Boolean));
      const remaining = encryptedQueue.filter((record) => (
        failedQueueIds.has(record.queue_id)
        || (Array.isArray(result.processed_queue_ids) && !processedQueueIds.has(record.queue_id))
        || (!Array.isArray(result.processed_queue_ids)
          && failures.length > 0
          && result.records_processed < queue.length)
      ));

      const writeTransaction = database.transaction(QUEUE_STORE, 'readwrite');
      const store = writeTransaction.objectStore(QUEUE_STORE);
      for (const record of encryptedQueue) store.delete(record.queue_id);
      for (const record of remaining) store.put(record);
      await transactionResult(writeTransaction);
      this.notifyQueueChange(remaining.length);
      window.dispatchEvent(new CustomEvent('cb_sync_complete', { detail: result }));
      return result;
    } catch (error) {
      window.dispatchEvent(new CustomEvent('cb_sync_error', { detail: error.message }));
      throw error;
    } finally {
      this.isFlushing = false;
    }
  }
}

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL
  || `${window.location.protocol}//${window.location.hostname}:8000`;
export const syncManager = new OfflineSyncManager(`${apiBaseUrl}/api/v1/sync/queue`);
