"""Behavioral regression tests; synthetic fixtures are NOT delivered sample artwork."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageDraw, ImageChops

spec=importlib.util.spec_from_file_location("pipeline",Path(__file__).with_name("sprite_pipeline.py"))
p=importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()
    def ref(self):
        im=Image.new("RGBA",(128,128))
        ImageDraw.Draw(im).ellipse((24,24,104,104),fill=(0,0,0,255))
        im.save(self.root/"reference.png")
    def sheet(self,offset=0):
        im=Image.new("RGBA",(512,512))
        draw=ImageDraw.Draw(im)
        for i in range(16):
            x,y=(i%4)*128,(i//4)*128
            draw.ellipse((x+25,y+25,x+100,y+105),fill=(20+offset,20,20,255))
            draw.ellipse((x+45,y+45,x+65+i,y+72),fill=(255,255,255,255))
            draw.ellipse((x+55,y+55,x+60,y+60),fill=(255,0,0,130))
        return im
    def test_input_modes_and_relative_path(self):
        self.ref()
        for request,mode in [({"prompt":"cat"},"text"),({"reference_image":"reference.png"},"image"),({"reference_image":"reference.png","prompt":"sleep"},"reference_text")]:
            value=p.normalize(request,self.root/"request.json")
            self.assertEqual(value["mode"],mode)
            if "reference_image" in request:
                self.assertEqual(value["reference_image"],str((self.root/"reference.png").resolve()))
    def test_reject_invalid_inputs(self):
        cases=[{}, {"prompt":"cat","size":199},{"prompt":"cat","fps":16},
               {"prompt":"cat","actions":["yawn","yawn","eat"]},
               {"prompt":"cat","actions":["../bad","sleep","eat"]},
               {"prompt":"cat","actions":["new","sleep","eat"]}]
        for case in cases:
            with self.assertRaises(ValueError): p.normalize(case,self.root/"r.json")
    def test_custom_action(self):
        r=p.normalize({"prompt":"cat","actions":["wave","sleep","eat"],"action_specs":{"wave":"Wave a paw then return"}},self.root/"r.json")
        self.assertIn("wave",r["actions"])
    def test_component_layout_and_speckle_removal(self):
        sheet=self.sheet()
        sheet.putpixel((4,4),(255,0,0,255))
        frames,boxes=p.component_frames(sheet,"fixture")
        self.assertEqual(len(frames),16)
        self.assertTrue(all(f.getchannel("A").getextrema()==(0,255) for f in frames))
        self.assertEqual(frames[0].getpixel((4,4))[3],0)
        empty=Image.new("RGBA",(512,512))
        with self.assertRaises(ValueError): p.component_frames(empty,"empty")
    def test_cumulative_timing(self):
        for fps in range(12,16):
            ds=p.durations(1000,fps,10)
            self.assertLessEqual(abs(sum(ds)-1000000/fps),5)
            self.assertTrue(all(d%10==0 and d>0 for d in ds))
    def test_alpha_and_clipping_rejected(self):
        with self.assertRaises(ValueError): p.alpha_bbox(Image.new("RGBA",(32,32),"white"),"opaque")
        with self.assertRaises(ValueError): p.alpha_bbox(Image.new("RGBA",(32,32)),"empty")
        im=Image.new("RGBA",(32,32)); ImageDraw.Draw(im).rectangle((0,5,20,20),fill="black")
        with self.assertRaises(ValueError): p.alpha_bbox(im,"clipped")
    def test_end_to_end_codecs_and_overwrite(self):
        self.ref()
        request=self.root/"request.json"
        p.write_json(request,{"prompt":"test character","size":200})
        job=self.root/"job"
        p.prepare(request,job)
        Image.open(self.root/"reference.png").save(job/"sources/character.png")
        for i,a in enumerate(["yawn","sleep","eat"]): self.sheet(i*20).save(job/f"sources/{a}.png")
        result=p.build(job)
        self.assertEqual(result["status"],"built_needs_visual_review")
        self.assertEqual(p.validate(job)["status"],"file_checks_passed")
        m=p.read_json(job/"manifest.json")
        self.assertEqual(m["visual_review"]["status"],"pending")
        self.assertEqual(len(m["actions"]),3)
        for a in m["actions"]:
            with Image.open(job/f"{a}.apng") as encoded:
                self.assertEqual(encoded.n_frames,16)
                for i in range(16):
                    encoded.seek(i)
                    with Image.open(job/f"frames/{a}/{i:03}.png") as source:
                        self.assertEqual(encoded.convert("RGBA").tobytes(),source.tobytes())
            with Image.open(job/f"{a}.gif") as encoded:
                for i in range(encoded.n_frames):
                    encoded.seek(i)
                    with Image.open(job/f"frames/{a}/{i:03}.png") as source:
                        expected=source.getchannel("A").point(lambda x:255 if x>=128 else 0)
                        actual=encoded.convert("RGBA").getchannel("A")
                        self.assertIsNone(ImageChops.difference(expected,actual).getbbox())
        with self.assertRaises(ValueError): p.prepare(request,job)
        with self.assertRaises(ValueError): p.build(job)

if __name__=="__main__": unittest.main(verbosity=2)
