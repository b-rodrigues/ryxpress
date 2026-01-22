from ryxpress import hello, __version__

def test_hello():
    assert hello() == "Hello from ryxpress!"

def test_version():
    assert isinstance(__version__, str)
