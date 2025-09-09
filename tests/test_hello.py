from rixpress import hello, __version__

def test_hello():
    assert hello() == "Hello from rixpress!"

def test_version():
    assert isinstance(__version__, str)
