"""Run existing tests in an isolated container with no production credentials."""
import os
os.environ['DATABASE_URL']='sqlite:///:memory:'
os.environ['ADMIN_USERNAME']=''
os.environ['ADMIN_PASSWORD']=''
os.environ['SECRET_KEY']='isolated-test-key'
import app  # Initialize the memory engine before test modules set their own defaults.
import faulthandler, sys, unittest, zipfile
faulthandler.dump_traceback_later(60, repeat=True)
zipfile.ZipFile('/checks/tests.zip').extractall('/tmp/trustmap-tests')
sys.path.insert(0, '/tmp/trustmap-tests')
suite=unittest.defaultTestLoader.discover('/tmp/trustmap-tests')
result=unittest.TextTestRunner(verbosity=2).run(suite)
faulthandler.cancel_dump_traceback_later()
sys.exit(not result.wasSuccessful())
