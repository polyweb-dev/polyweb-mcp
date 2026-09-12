1. When you use the Brave search, the request is not updated, so the usage isn't ticking down. Check that out. Quota details can probably show the exact usage, like we already have a progress bar showing the approximate usage, and I don't think it is ticking down; that needs to be verified. 

2. Exa is still to be linked; it has not been linked properly yet.

3. Auth migration for all keys

| What You Described | How It Works in the System |
| :--- | :--- |
| **1. User can set their own AES-256 key...** | The user can set `FREESEARCH_ENCRYPTION_KEY=my-custom-passphrase` in `docker-compose.yml` or `.env`. FreeSearch will use it directly. |
| **2. ...or skip it, and it will be auto-generated** | If omitted, FreeSearch auto-generates a cryptographically strong 256-bit key and saves it to `/data/.secret_key` with strict `0600` permissions. |
| **3. Key is stored in the Docker volume** | `/data/.secret_key` lives inside the mounted volume (`-v freesearch_data:/data`), surviving all container restarts and image updates. |
| **4. All incoming keys encrypted before storing in DB** | Whenever the user saves a key in the Web UI, Python encrypts it with AES-256 first. Only the unreadable ciphertext blob (`gAAAAABn...`) touches SQLite. |
| **5. Database is in the same Docker volume** | Both `/data/freesearch.db` and `/data/.secret_key` reside together in the same persistent `/data` volume. One single volume to manage, mount, or backup. |