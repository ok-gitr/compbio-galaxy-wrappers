import requests
import argparse
import gzip

def supply_args():
  parser = argparse.ArgumentParser(description='')
  parser.add_argument('-id', help="Moon ID")
  parser.add_argument('-user', help="Moon user email")
  parser.add_argument('-token', help="Moon API token")
  args = parser.parse_args()
  return args
  
def main():
  args = supply_args()
  parameters = {"user_token": args.token, "user_email": args.email}
  url = "https://oregon.moon.diploid.com/samples/" + args.id + "/download_report"
  report = requests.get(url, params=parameters)
  report_text = gzip.open("allRareVariants.tsv.gz.gz", 'wb')
  report_text.write(report.content)
  report_text.close()

if __name__ == "__main__":
  main()
