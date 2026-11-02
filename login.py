import hashlib
import hmac
import os


_USER_STORE: dict[str, dict] = {}


def _hash_password(password: str, salt: bytes) -> str:
    """Return a hex-encoded HMAC-SHA256 hash of *password* using *salt*."""
    return hmac.new(salt, password.encode("utf-8"), hashlib.sha256).hexdigest()


def register_user(username: str, password: str) -> bool:
    """
    Register a new user with a hashed password.

    Args:
        username: The desired username (must be non-empty and unique).
        password: The plain-text password (must be at least 6 characters).

    Returns:
        True  – registration succeeded.
        False – username already exists or inputs are invalid.
    """
    if not username or not password:
        print("[register] Username and password must not be empty.")
        return False

    if len(password) < 6:
        print("[register] Password must be at least 6 characters long.")
        return False

    if username in _USER_STORE:
        print(f"[register] Username '{username}' is already taken.")
        return False

    salt = os.urandom(32)
    password_hash = _hash_password(password, salt)
    _USER_STORE[username] = {"password_hash": password_hash, "salt": salt}
    print(f"[register] User '{username}' registered successfully.")
    return True


def login(username: str, password: str) -> bool:
    """
    Authenticate a user by verifying their credentials.

    Args:
        username: The username to look up.
        password: The plain-text password to verify.

    Returns:
        True  – credentials are valid (login successful).
        False – username not found or password is incorrect.
    """
    if not username or not password:
        print("[login] Username and password must not be empty.")
        return False

    user = _USER_STORE.get(username)
    if user is None:
        print(f"[login] User '{username}' does not exist.")
        return False

    expected_hash = _hash_password(password, user["salt"])

    # Use hmac.compare_digest to prevent timing attacks
    if hmac.compare_digest(expected_hash, user["password_hash"]):
        print(f"[login] User '{username}' logged in successfully.")
        return True

    print("[login] Incorrect password.")
    return False


def logout(username: str) -> None:
    """
    Log out a user (placeholder for session / token invalidation).

    Args:
        username: The username of the user to log out.
    """
    if username in _USER_STORE:
        print(f"[logout] User '{username}' has been logged out.")
    else:
        print(f"[logout] Unknown user '{username}'.")


if __name__ == "__main__":
    # Register two users
    register_user("alice", "secret123")
    register_user("bob", "pass!456")

    print()

    # Successful login
    login("alice", "secret123")

    # Wrong password
    login("alice", "wrongpass")

    # Non-existent user
    login("charlie", "any_password")

    print()

    # Logout
    logout("alice")
    logout("charlie")
