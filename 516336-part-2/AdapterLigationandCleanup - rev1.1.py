def get_values(*names):
    import json
    _all_values = json.loads("""{"samples":96,"m300_mount":"right","p300_mount":"left","mag_engage_height":7.8}""")
    return [_all_values[n] for n in names]


from opentrons import protocol_api, types
from opentrons import protocol_api, types
from opentrons import *
import math
import pandas as pd
import csv

metadata = {
    'protocolName': 'Ligation Sequencing Kit: Adapter Ligation and Clean-Up',
    'author': 'Aishah Al Zeyoudi <aishah.alzeyoudi@g42.ai>',
    'description': 'Custom Protocol Request',
    'apiLevel': '2.10'
}
water_run = True
Source_position = []
Target_position = []

file_input_ot2 = '/data/user_files/input.csv'

df = pd.read_csv(file_input_ot2)

for i in range(len(df)):
    Source_position.append(df['Source'][i])
    # Target_position.append(df['Target'][i])
    Target_position = ['A1', 'B1', 'A2', 'B2', 'A3', 'B3', 'A4', 'B4', 'A5', 'B5', 'A6', 'B6', 'A7', 'B7', 'A8', 'B8', 'A9', 'B9', 'A10', 'B10', 'A11', 'B11', 'A12', 'B12']

def run(ctx):

    [samples, m300_mount, p300_mount,
        mag_engage_height] = get_values(  # noqa: F821
        "samples", "m300_mount", "p300_mount", "mag_engage_height")


    ai = math.ceil(len(df)/4)

    cols = math.ceil(len(df)/8)

    # Load Labware
    tc_mod = ctx.load_module('Thermocycler Module')     # loaded the TC mod even not used to avoid collision
    tc_plate = tc_mod.load_labware('biorad_96_wellplate_200ul_pcr')
    mag_mod = ctx.load_module('magnetic module gen2', '1')
    mag_plate = mag_mod.load_labware('thermofisher_96_midi_storage_plate_800ul')
    temp_mod = ctx.load_module('temperature module gen2', 4)
    temp_rack = temp_mod.load_labware('opentrons_24_aluminumblock_generic_2ml_screwcap')
    sample_plate = ctx.load_labware('biorad_96_wellplate_200ul_pcr', 2)
    reservoir = ctx.load_labware('nest_12_reservoir_15ml', 3)
    tipracks_multi = [ctx.load_labware('opentrons_96_tiprack_300ul', slot) for slot in [6, 9]]
    # tipracks_multi = ctx.load_labware('opentrons_96_tiprack_300ul', 6, 9)
    tipsracks_single = ctx.load_labware('opentrons_96_tiprack_300ul', 5)
    trash = ctx.loaded_labwares[12]['A1']

    # tipracks_mm_aliquot = ctx.load_labware('opentrons_96_tiprack_300ul', 6)
    tip_positions = ['A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'A7', 'A8', 'A9', 'A10', 'A11', 'A12']
    # Load Pipettes
    m300 = ctx.load_instrument('p300_multi_gen2', m300_mount,
                               tip_racks=tipracks_multi)
    # p300 = ctx.load_instrument('p300_single_gen2', p300_mount,
    #                            tip_racks=[tipsracks_single])

    # REAGENTS
    ampure_beads = reservoir['A12']
    elution_buff = reservoir['A5']
    mm = temp_rack['A1']

    # SAMPLE WELLS
    mag_plate_wells = mag_plate.rows()[0][:cols]
    sample_plate_wells = sample_plate.rows()[0][:cols]
    #tmp_plate_wells =

    # HELPER FUNCTIONS
    def pick_up(pip):
        """Function that can be used instead of .pick_up_tip() that will pause
        robot when robot runs out of tips, prompting user to replace tips
        before resuming"""
        try:
            pip.pick_up_tip()
        except protocol_api.labware.OutOfTipsError:
            pip.home()
            ctx.pause("Replace the tips")
            pip.reset_tipracks()
            pip.pick_up_tip()

    def remove_supernatant(vol, src, dest, side):
        m300.flow_rate.aspirate = 20
        m300.aspirate(10, src.top())
        while vol > 300:
            m300.aspirate(
                300, src.bottom().move(types.Point(x=side, y=0, z=0.5)))
            m300.dispense(300, dest)
            m300.aspirate(10, dest)
            vol -= 300
        m300.aspirate(vol, src.bottom(1.5).move(types.Point(x=side, y=0, z=0.5)))
        m300.dispense(vol, dest)
        m300.dispense(10, dest)
        m300.flow_rate.aspirate = 50

    sides = [-1, 1] * 6
    sides = sides[:cols]

    # ENGAGE MAGNET FUNCTION
    def magnet(delay_mins):
        mag_mod.engage(height_from_base=mag_engage_height)
        ctx.delay(minutes=delay_mins, msg='Allowing beads to settle.')

    # VOLUME TRACKING
    class VolTracker:
        def __init__(self, labware, well_vol, pip_type='single',
                     mode='reagent', start=0, end=12, msg='Reset Labware'):
            try:
                self.labware_wells = dict.fromkeys(
                    labware.wells()[start:end], 0)
            except Exception:
                self.labware_wells = dict.fromkeys(
                    labware, 0)
            self.labware_wells_backup = self.labware_wells.copy()
            self.well_vol = well_vol
            self.pip_type = pip_type
            self.mode = mode
            self.start = start
            self.end = end
            self.msg = msg

        def tracker(self, vol):
            '''tracker() will track how much liquid
            was used up per well. If the volume of
            a given well is greater than self.well_vol
            it will remove it from the dictionary and iterate
            to the next well which will act as the reservoir.'''
            well = next(iter(self.labware_wells))
            if self.labware_wells[well] + vol >= 12000:
                del self.labware_wells[well]
                if len(self.labware_wells) < 1:
                    ctx.pause(self.msg)
                    self.labware_wells = self.labware_wells_backup.copy()
                well = next(iter(self.labware_wells))
            if self.pip_type == 'multi':
                self.labware_wells[well] = self.labware_wells[well] + vol*8
            elif self.pip_type == 'single':
                self.labware_wells[well] = self.labware_wells[well] + vol
            if self.mode == 'waste':
                ctx.comment(f'''{well}: {int(self.labware_wells[well])} uL of
                            total waste''')
            else:
                ctx.comment(f'''{int(self.labware_wells[well])} uL of liquid
                            used from {well}''')
            return well

    fragBufferTrack = VolTracker(reservoir, 12000, 'multi', start=0, end=4,
                                 msg='Replenish Fragment Buffer')

    # PROTOCOL STEPS

    # TRANSFER ADAPTER LIGATION MIX TO SAMPLES ON PCR PLATE (1)
    def transfer_adapter_ligation():
        temp_mod.set_temperature(8)
        ctx.pause('Add the Mastermix tube to the cooling block position A1 and resume.')
        # p300.transfer(40, mm, sample_plate_wells, new_tip='always', mix_after=(3, 30))
        m300.pick_up_tip(tipsracks_single['A1'])
        # y = 0
        # m300.pick_up_tip(tipracks_multi[tip_positions[y]])
        for i in range(len(Target_position[:ai])):
            m300.aspirate(40, mm)
            m300.dispense(40, mag_plate[Target_position[i]])
            # m300.mix(3, 30, mag_plate[Target_position[i]])
            m300.blow_out()
        if water_run:
            m300.return_tip(home_after=False)
        else:
            m300.drop_tip(home_after=False)
        temp_mod.deactivate()
    # TRANSFER SAMPLES FROM SAMPLE PLATE TO MAGNETIC MODULE (2)
    def transfer_samples_from_sample_plate_to_mag_mod():
        for src, dest in zip(sample_plate_wells, mag_plate_wells):
            # m300.pick_up_tip()
            m300.transfer(60, src, dest, mix_after=(5, 80), new_tip='always', trash=False)
            # m300.mix(5, 80)
            # m300.drop_tip(home_after=False)
            # if water_run:
            #     m300.drop_tip(home_after=False)
            #     # m300.return_tip(home_after=False)
            # else:
            #     m300.drop_tip(home_after=False, trash=false)

    # ADD AMPURE XP BEADS TO MAGNETIC MODULE (3)
    def add_ampure_xp_beads_to_mag_mod():
        ctx.pause('''Add Ampure Beads manually to reservoir in slot 3 Position 12.''')
        for well in mag_plate_wells:
            # pick_up(m300)
            # m300.pick_up_tip()
            m300.transfer(40, ampure_beads, well, new_tip='always',
                          mix_before=(3, 40), mix_after=(3, 50), trash=False)
            # m300.drop_tip(home_after=False)
            # if water_run:
            #     m300.return_tip(home_after=False)
            # else:
            #     m300.drop_tip(home_after=False)

    # INCUBATION AND REMOVE SUPERNATANT (4)
    def incubation_remove_supernatant():
        # Pause for Hula Mixer/Spin Down (4)
        ctx.pause('''Incubate on Hula Mixer for 5 minutes and spin down the samples.
                     Then place back on the magnet and click resume.''')
        # Engage Magnet and Delay for 5 Minutes (4)
        magnet(5)

        # Remove Supernatant (4)
        for well, side in zip(mag_plate_wells, sides):
            pick_up(m300)
            remove_supernatant(140, well, trash, side)
            # m300.drop_tip(home_after=False)
            if water_run:
                m300.return_tip(home_after=False)
            else:
                m300.drop_tip(home_after=False)

    # WASH BEADS WITH FRAGMENT BUFFER (5)
    def wash_beads_with_fragment_buffer():
        ctx.comment('Wash Beads with Fragment Buffer (5)')
        for _ in range(2):
            # Wash Beads with Fragment Buffer (5)
            for well in mag_plate_wells:
                pick_up(m300)
                m300.aspirate(250, fragBufferTrack.tracker(250))
                m300.dispense(250, well.bottom(4))
                m300.mix(3, 100)
                # m300.drop_tip(home_after=False)
                if water_run:
                    m300.return_tip(home_after=False)
                else:
                    m300.drop_tip(home_after=False)
            # Pellet Beads
            magnet(5)
            # Remove Supernatant (5)
            for well, side in zip(mag_plate_wells, sides):
                pick_up(m300)
                remove_supernatant(250, well, trash, side)

                if water_run:
                    m300.return_tip(home_after=False)
                else:
                    m300.drop_tip(home_after=False)

    # PAUSE THE PROTOCOL & REMOVE THE SAMPLES FOR SPIN DOWN (6)
    def spin_down_remove_supernatant_add_elution():
        mag_mod.disengage()
        ctx.pause('''Spin down and place samples back on the maget.
                  Then click resume.''')
        magnet(1)

        # Remove Residual Supernatant (6)
        for well, side in zip(mag_plate_wells, sides):
            pick_up(m300)
            remove_supernatant(250, well, trash, side)
            # m300.drop_tip(home_after=False)
            if water_run:
                m300.return_tip(home_after=False)
            else:
                m300.drop_tip(home_after=False)

    # ADD 15ul OF ELUTION BUFFER (7)
    def add_elution_buffer():
        mag_mod.disengage()
        # pick_up(m300)
        # m300.distribute(
        #     volume=15,
        #     source=elution_buff,
        #     dest=mag_plate_wells,
        #     blow_out=True,
        #     blowout_location='source well')
        # m300.drop_tip(home_after=False)

        # pick_up(m300)
        # for g in range(len(Target_position)):
        #     pick_up(m300)
        #     m300.aspirate(200, elution_buff)
        #     m300.dispense(15, mag_plate[Target_position[g]])

        for well in mag_plate_wells:
            pick_up(m300)
            # m300.transfer(15, elution_buff, well.bottom(2), new_tip='never')
            m300.aspirate(volume=28,
                          location=elution_buff)
            m300.dispense(volume=28,
                          location=well.bottom(2))
            m300.mix(repetitions=3,
                     volume=28,
                     location=well.bottom(2))
            m300.blow_out(location=well.bottom(2))
            if water_run:
                m300.return_tip(home_after=False)
            else:
                m300.drop_tip(home_after=False)

        # ctx.delay(minutes=10,
        #           msg='Incubating at Room Temperature for 10 minutes.')
        ctx.pause('''Shake, spin down and incubate at Room Temperature for 10 minutes.''')
        # # m300.drop_tip(home_after=False)

    # ENGAGE MAGNET FOR 5 MINUTES(8)
    def engage_magnet():
        magnet(5)

    # TRANSFER ELUATE INTO FINAL SAMPLE PLATE (9)
    def transfer_eluate():
        ctx.pause('''Replace old BioRad PCR plate with new BioRad PCR plate for
                  storing the new DNA library.''')
        for well, dest, side in zip(mag_plate_wells, sample_plate_wells, sides):
            pick_up(m300)
            remove_supernatant(27, well, dest, side)
            m300.drop_tip(home_after=False)

    ## PROCESS STEPS
    transfer_adapter_ligation()
    transfer_samples_from_sample_plate_to_mag_mod()
    add_ampure_xp_beads_to_mag_mod()
    incubation_remove_supernatant()
    wash_beads_with_fragment_buffer()
    spin_down_remove_supernatant_add_elution()
    add_elution_buffer()
    engage_magnet()
    transfer_eluate()

    temp_mod.deactivate()
    mag_mod.disengage()
