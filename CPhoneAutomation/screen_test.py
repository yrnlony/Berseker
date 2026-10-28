import uiautomator2 as u2

d = u2.connect()

print("Connected:", d.info)

d.screenshot("screen.png")

xml = d.dump_hierarchy()

with open("screen.xml", "w", encoding="utf-8") as f:
    f.write(xml)

print("Screenshot saved as screen.png")
print("UI hierarchy saved as screen.xml")
