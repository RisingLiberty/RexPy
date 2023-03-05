echo off

pushd %~dp0

rmdir /S /Q dist

py -m pip install --upgrade build
py -m build
py -m pip install --upgrade twine
py -m twine upload --repository testpypi dist/*

popd