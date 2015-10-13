import requests
import sys
import xml.etree.ElementTree as ET
import datetime
import time
import subprocess
import qgreports.config.settings

__author__ = "dmwoods38"
qualys_api_url = qgreports.config.settings.QualysAPI['url']
xreq_header = {"X-Requested-With": "Python"}
session_path = "/api/2.0/fo/session/"		
debug = True 

# TODO: Lots of small fixes

# Params: Strings for username and password
# Optional headers to include with login request
# Return: Returns session 
def login(username, password, headers=xreq_header, params=None):
    if params is None:
        params = {}
    params.update({"action": "login", "username": username,
                   "password": password})
    r = requests.Session()
    s = request(params, r, session_path, headers=headers, verb="post")
    if check_status(s):
        print "Successfully logged in"
        return r
    else:
        print "There was an error logging you in"
        if debug:
            print s.text


# Params: Session to logout of 
#         Optional headers to include with logout request
def logout(session, headers=xreq_header, params=None):
    if params is None:
        params = {}
    params.update({"action": "logout"})
    s = request(params, session, session_path, headers=headers, verb="post")
    if check_status(s):
        print "Successfully logged out"
    else:
        print "There was an error logging you out"


# Params: Takes in a Response object
# Description: Error checking for the response codes
def check_status(response):
    if response.status_code == 200:
        return True
    else:
        print "Error with the request"
        print "Status code: " + str(response.status_code)
        return False


# Params
def request(params, session, dest_url, verb='POST', headers=xreq_header,
                data=""):
    if debug:
        print "HTTP Verb" + verb
        print "URL: " + qualys_api_url+dest_url
        print "Params: " + str(params)
    try:
        if verb.upper() == 'GET':
            s = session.get(qualys_api_url+dest_url, params=params, headers=headers)
        elif verb.upper() == 'POST':
            s = session.post(qualys_api_url+dest_url, params=params, headers=headers, data=data)
        else:
            print "Unsupported HTTP verb: " + verb
            sys.exit(2)
        if debug:
            print "status_code: " + str(s.status_code)
    except Exception as e:
        print e
        print "Retrying..."
        try:
            s = session.post(qualys_api_url+dest_url, params=params, headers=headers, data=data)
        except Exception as e:
            print e
            sys.exit(2)
    return s


# Return: Returns XML with the VM scan list
def get_scans(session, params=None):
    if params is None:
        params = {}
    params.update({"action": "list"})
    dest_url = "/api/2.0/fo/scan/"
    response = request(params, session, dest_url)
    if check_status(response):
        return response.text
    else:
        print "Error retrieving scan list"
        sys.exit(2)


# Returns a dict of processed and unprocessed scans
#     which is in turn a dict of scan title and scan references
def get_scan_refs(scan_names, session, params=None, latest=True,
                  scans_list=None):
    if params is None:
        params = {}
    if scans_list is None:
        scans_list = get_scans(session, params)
    scan_xml = ET.fromstring(scans_list.encode('ascii', 'ignore'))
    scan_xpath = "./RESPONSE/SCAN_LIST/SCAN/"
    scans_with_refs = {"processed": {}, "unprocessed": {}}
    for scan in scan_names:
        scan_refs_processed = []
        scan_refs_unprocessed = []
        if latest:
            scan_list = [scan_xml.find(scan_xpath + "[TITLE='" + scan + "']")]
        else:
            scan_list = scan_xml.findall(scan_xpath + "[TITLE='" + scan + "']")
        for node in scan_list:
            if int(node.find("./PROCESSED").text):
                scan_refs_processed.append(node.find("./REF").text)
            else:
                scan_refs_unprocessed.append(node.find("./REF").text)
        if debug:
            print "processed: " + str(scan_refs_processed)
            print "unprocessed: " + str(scan_refs_unprocessed)
        scans_with_refs['processed'].update({scan:scan_refs_processed})
        scans_with_refs['unprocessed'].update({scan:scan_refs_unprocessed})
    return scans_with_refs

# TODO: Change to return report objects.
# Description: Launches scan reports and then returns the refs
#              with the corresponding report ids
def launch_scan_reports(scans_with_refs, session, formats=None, params=None):
    if formats is None:
        formats = ['csv']
    if params is None:
        params = {}
    params.update({"report_type": "Scan", "action": "launch"})
    params.update({"template_id":
                       qgreports.config.settings.QualysAPI['scan_template']})
    dest_url = "/api/2.0/fo/report/"
    refs_with_ids = {}
    item_xpath = "./RESPONSE/ITEM_LIST/ITEM"
    max_num_xpath = "./RESPONSE/TEXT"
    max_report_string = "Max number of allowed reports"
    processed = scans_with_refs['processed']
    unprocessed = scans_with_refs['unprocessed']
    for scan in processed:
        for ref in processed[scan]:
            params.update({"report_refs":ref})
            ids = []
            for output_format in formats:
                params.update({"output_format": output_format})
                # make request then parse xml for report id
                response = request(params, session, dest_url)
                report_xml = ET.fromstring(response.text.encode('ascii', 'ignore'))
                while max_report_string in report_xml.find(max_num_xpath).text:
                    if debug:
                        print "Max reports running already. Waiting 2 min..."
                    time.sleep(120)
                    response = request(params, session, dest_url)
                    report_xml = ET.fromstring(response.text.encode('ascii',
                                                                    'ignore'))
                items = report_xml.findall(item_xpath)
                for item in items:
                    if item.find("./KEY").text.upper() == "ID":
                        ids.append(item.find("./VALUE").text)
                        break
                if debug:
                    print response.text
            refs_with_ids.update({ref: ids})

    if len(unprocessed):
        with open("/root/unprocessed.log", "a") as f:
            f.write("Unprocessed for " + datetime.date.today().__str__())
            f.write(str(unprocessed))

    return refs_with_ids

# TODO: Change to take in report objects and return report objects.
# Check that the report is finished before we try to download them.
def check_report_status(refs_with_ids, session):
    params = {"action": "list"}
    dest_url = "/api/2.0/fo/report/"
    report_list = request(params, session, dest_url)
    report_list_xml = ET.fromstring(report_list.text)

    print "refs_with_ids : " + refs_with_ids.__str__()
    refs_with_ids_by_status = {"Finished":{}, "Unfinished":{}}
    # Report share limit text: Your Report Share user limit has been reached. This report will not be saved.
    # TODO add checking for report share limit and automatic deletion from the queue.
    report_limit = "Your Report Share user limit has been reached. " \
                   "This report will not be saved."
    report_limit_xpath = "./RESPONSE/TEXT"

    report_xpath = "./RESPONSE/REPORT_LIST/REPORT"
    for ref, ids in refs_with_ids.iteritems():
        refs_with_ids_by_status['Finished'].update({ref:[]})
        refs_with_ids_by_status['Unfinished'].update({ref:[]})
        for report in report_list_xml.findall(report_xpath):
            for id in ids:
                if report.find("./ID").text == id:
                    state = report.find("./STATUS/STATE").text
                    if state == "Finished":
                        refs_with_ids_by_status['Finished'][ref].append(id)
                    elif state == "Running" or state == "Submitted":
                        refs_with_ids_by_status['Unfinished'][ref].append(id)
                    else:
                        print "The report won't complete"
                        print "Report status: " + state
                        sys.exit(2)
    return refs_with_ids_by_status


# Download reports
# TODO: Create objects that store scan ref(s), report id(s), and report names
def get_reports(refs_with_ids, scans_with_refs, snames_with_rnames, session):
    params = {"action": "fetch"}
    dest_url = "/api/2.0/fo/report/"
    today = datetime.date.today().__str__()
    report_path = "/root/reports/"
    report_prefix = ""
    report_suffix = " " + today
    print "Trying to get reports..."
    print "refs_with_ids : " + refs_with_ids.__str__()
    print "scans_with_refs : " + scans_with_refs.__str__()
    print "snames_with_rnames : " + snames_with_rnames.__str__()
    for scan_ref,report_ids in refs_with_ids.iteritems():
        for report_id in report_ids:
            for scan_name,refs in scans_with_refs.iteritems():
                if scan_ref in refs:
                    params.update({"id":report_id})
                    report_name = snames_with_rnames[scan_name]
                    if not len(report_name):
                        report_name = scan_name
                    report_name = report_prefix + report_name + report_suffix
                    with open(report_path + report_name, "ab") as f:
                        response = request(params, session, dest_url)
                        check_status(response)
                        f.write(response.content)
                    # check filetype and rename with appropriate extension
                    command = "file " + report_path.replace(" ", "\ ") + report_name.replace(" ", "\ ")
                    command += " | cut -d':' -f2"
                    filetype = subprocess.check_output(command, shell=True)
                    filetype = filetype.strip()

                    fullname = report_path.replace(" ", "\ ") + \
                               report_name.replace(" ", "\ ") + filetype

                    command = "mv " + report_path.replace(" ", "\ ")
                    command = command + report_name.replace(" ", "\ ") + \
                              " " + fullname
                    subprocess.call(command, shell=True)


# Returns API scan results, not the same as a scan report. Much less detail.
def get_scan_results(scans_with_refs, session, scans_with_files,
                            folder="/root/reports/",
                            format="csv", params={}):
    params.update({"action":"fetch","mode":"brief", "output_format":format})
    dest_url = "/api/2.0/fo/scan/"
    processed = scans_with_refs['processed']
    unprocessed = scans_with_refs['unprocessed']
    for scan in processed:
        for ref in processed[scan]:
            params.update({"scan_ref":ref})
            response = request(params, session, dest_url)
            file = scans_with_files[scan] if scans_with_files[scan] else scan
            filename = folder + file
            filename = filename +"_"+datetime.date.today().__str__() + "." + format
            with open(filename, "a") as f:
                f.write(response.text)

    if len(unprocessed):
        with open("/root/unprocessed.log", "a") as f:
            f.write("Unprocessed for " + datetime.date.today().__str__())
            f.write(str(unprocessed))

#def get_hosts_list(session, ag_names=