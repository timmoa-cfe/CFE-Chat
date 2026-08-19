================================================================================
CFE-Chat v.5.0 — Ultimate Autonomous P2P Local Messenger
================================================================================
Description:
    A fully decentralized, serverless, peer-to-peer desktop chat application 
    built for isolated local area networks (LAN), home "domonets", or mesh 
    subnets. Operates strictly wire-to-wire over standard TCP/UDP sockets with 
    zero external server, cloud database, or internet dependency.

Core Systems:
    - Networking: Thread-safe backend via ThreadPoolExecutor decoupled from GUI.
    - Autodiscovery: Zero-configuration local node discovery using UDP broadcasts.
    - File Sharing: High-speed chunked binary streaming with dynamic progress bars.
    - Encryption: Native secure communication layer powered by the Cryptography library.
    - Interface: High-density CustomTkinter dark GUI with a text formatting toolbar.
    - Session Logging: Automatic history mapping to local log.txt for valid DM peers.

Dependencies & Prerequisites:
    Ensure Python 3.13+ is installed, then run the environment setup:
    $ python -m pip install customtkinter cryptography pillow

Execution:
    Run natively using the Python interpreter:
    $ python3 cfe_chat_v5.py