"""
Shared SPI bus lock to prevent contention between displays.
"""

import threading

# Global SPI lock - all SPI operations should acquire this
spi_lock = threading.Lock()
