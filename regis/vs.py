import subprocess
import json
import regis.diagnostics

class _VisualStudioCatalog():
  def __init__(self, jsonData : dict):
    self.build_branch : str = jsonData['buildBranch']
    self.build_version : str = jsonData['buildVersion']
    self.id : str = jsonData['id']
    self.local_build : str = jsonData['localBuild']
    self.manifest_name : str = jsonData['manifestName']
    self.manifest_type : str = jsonData['manifestType']
    self.product_display_version : str = jsonData['productDisplayVersion']
    self.product_line : str = jsonData['productLine']
    self.product_line_version : str = jsonData['productLineVersion']
    self.product_milestone : str = jsonData['productMilestone']
    self.product_milestone_is_pre_release : str = jsonData['productMilestoneIsPreRelease']
    self.product_name : str = jsonData['productName']
    self.product_patch_version : str = jsonData['productPatchVersion']
    self.product_pre_release_milestone_suffix : str = jsonData['productPreReleaseMilestoneSuffix']
    self.product_semantic_version : str = jsonData['productSemanticVersion']
    self.required_engine_version : str = jsonData['requiredEngineVersion']

class _VisualStudioProperties():
  def __init__(self, jsonData : dict):
    self.campaign_id = jsonData['campaignId']
    self.channel_manifest_id = jsonData['channelManifestId']
    self.nickname = jsonData['nickname']
    self.setup_engine_filepath = jsonData['setupEngineFilePath']

# JSON data is loaded as output from the vswhere.exe program
# which comes from a visual studio install
class VisualStudioInstall():
  def __init__(self, jsonData):
    self.instance_id : str = jsonData['instanceId']
    self.install_date : str = jsonData['installDate']
    self.installation_name : str = jsonData['installationName']
    self.installation_path : str = jsonData['installationPath']
    self.installation_version : str = jsonData['installationVersion']
    self.product_id : str = jsonData['productId']
    self.product_path : str = jsonData['productPath']
    self.state : int = jsonData['state']
    self.is_complete : bool = jsonData['isComplete']
    self.is_launchable : bool = jsonData['isLaunchable']
    self.is_prerelease : bool = jsonData['isPrerelease']
    self.is_reboot_required : bool = jsonData['isRebootRequired']
    self.display_name : str = jsonData['displayName']
    self.description : str = jsonData['description']
    self.channel_id : str = jsonData['channelId']
    self.channel_url : str = jsonData['channelUri']
    self.engine_path : str = jsonData['enginePath']
    self.installed_channel_id : str = jsonData['installedChannelId']
    self.installed_channel_url : str = jsonData['installedChannelUri']
    self.release_notes : str = jsonData['releaseNotes']
    self.third_party_notices : str = jsonData['thirdPartyNotices']
    self.update_date : str = jsonData['updateDate']
    self.catalag = _VisualStudioCatalog(jsonData['catalog'])
    self.properties = _VisualStudioProperties(jsonData['properties'])

def installed_versions():
  vswhere_path = r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
  output = subprocess.getoutput(f'"{vswhere_path}" -format json')
  installed_versions : list[VisualStudioInstall] = []

  try:
    jsondata = json.loads(output)
    for installed_version in jsondata:
      installed_versions.append(VisualStudioInstall(installed_version))
  except Exception as ex:
    regis.diagnostics.log_warn(f'Failed to load visual studio versions.')
    regis.diagnostics.log_warn(f'Json data could not be loaded from vswhere.exe')
    regis.diagnostics.log_warn(f'Exception: {ex}')

  return installed_versions
